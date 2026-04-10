# Tool Architecture Standardization

**Date:** 2026-04-03
**Status:** Draft
**Goal:** Standardize tool implementation patterns to prevent recurring API integration bugs and reduce boilerplate.

## Problem

Every new API-based tool hand-rolls its own HTTP client, polling loop, error handling, and parameter coercion. This leads to:
- Wrong payload shapes (music_gen nested when API wants flat)
- Missing required fields (callBackUrl)
- Incorrect limits (prompt length, model names)
- Inconsistent error handling (some return success=True on failure)
- Duplicate polling logic (image_gen and music_gen both poll)
- Parameter type mismatches (boolean vs string for Groq compat)

As we add more tools (CLI-driven, MCP bridges, more APIs), this gets worse.

## Design

### 1. Shared HTTP Client Mixin for API Tools

```python
class APIToolMixin:
    """Shared HTTP patterns for tools that call external APIs."""

    _http: httpx.AsyncClient | None = None

    @property
    def http(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=30)
        return self._http

    async def api_post(self, url: str, payload: dict, api_key: str) -> dict:
        """POST JSON to an API with standard error handling."""
        resp = await self.http.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
        )
        data = resp.json()
        if resp.status_code >= 400:
            raise ToolAPIError(resp.status_code, data.get("msg") or data.get("error", "Unknown error"))
        return data

    async def api_get(self, url: str, api_key: str, params: dict = None) -> dict:
        """GET from an API with standard error handling."""
        resp = await self.http.get(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            params=params,
        )
        data = resp.json()
        if resp.status_code >= 400:
            raise ToolAPIError(resp.status_code, data.get("msg") or data.get("error", "Unknown error"))
        return data

    async def poll_until(
        self,
        url: str,
        api_key: str,
        params: dict,
        success_check: Callable[[dict], bool],
        failure_check: Callable[[dict], bool],
        extract: Callable[[dict], Any],
        max_seconds: float = 180,
        initial_delay: float = 5.0,
        max_delay: float = 15.0,
    ) -> Any:
        """Generic polling loop with exponential backoff."""
        delay = initial_delay
        elapsed = 0.0
        while elapsed < max_seconds:
            await asyncio.sleep(delay)
            elapsed += delay
            data = await self.api_get(url, api_key, params)
            if success_check(data):
                return extract(data)
            if failure_check(data):
                raise ToolAPIError(0, f"Task failed: {data}")
            delay = min(delay * 1.5, max_delay)
        raise ToolAPIError(0, "Polling timed out")
```

### 2. Parameter Coercion in BaseTool

Instead of each tool manually coercing `"false"` to `False`, the executor should coerce parameters against the schema before calling `execute()`:

```python
def _coerce_params(params: dict, schema: dict) -> dict:
    """Coerce parameter types to match the tool's schema."""
    properties = schema.get("properties", {})
    for key, spec in properties.items():
        if key not in params:
            continue
        if spec.get("type") == "boolean" or spec.get("enum") == ["true", "false"]:
            params[key] = str(params[key]).lower() == "true"
        elif spec.get("type") == "integer":
            params[key] = int(params[key])
        elif spec.get("type") == "number":
            params[key] = float(params[key])
    return params
```

This goes in the executor, not each tool.

### 3. Tool Types

Formalize the three tool types:

| Type | Base Class | Examples |
|------|-----------|----------|
| **Local** | `BaseTool` | code, file, notebook, kanban, artifacts |
| **API** | `APITool(BaseTool, APIToolMixin)` | image_gen, music_gen, email, calendar |
| **MCP** | `MCPToolBridge` (already exists) | MCP server tools |

Future additions:
- **CLI** tools: wrap shell commands with timeout/sandbox
- **Plugin** tools: loaded dynamically from plugins/

### 4. API Tool Template

New API tools follow this pattern:

```python
class MyAPITool(APITool):
    name = "my_tool"
    category = "create"
    description = "..."
    parameters_schema = {...}

    # API reference URL — helps future maintainers verify the implementation
    API_DOCS = "https://docs.example.com/api/my-endpoint"

    def __init__(self, api_key: str, ...):
        self._api_key = api_key

    async def execute(self, params: dict) -> ToolResult:
        # params are already coerced by executor
        result = await self.api_post(
            "https://api.example.com/v1/generate",
            payload={...},
            api_key=self._api_key,
        )
        return ToolResult(success=True, data=...)
```

## Migration Path

1. Create `odigos/tools/api_tool.py` with `APIToolMixin`, `APITool`, `ToolAPIError`
2. Add `_coerce_params` to executor (before `execute()` call)
3. Migrate image_gen and music_gen to use `APITool`
4. Migrate email, calendar tools
5. New tools use the template

## What This Does NOT Change

- Tool registration (bootstrap.py)
- Tool discovery (find_tools)
- MCP bridge (already standardized)
- Local tools (code, file, notebook — no API calls)
- ToolResult/ToolContract format
