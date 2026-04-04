# API Tool Foundation Design

**Date:** 2026-04-04
**Status:** Approved
**Goal:** Standardize tool implementation with base classes for API and CLI tools, parameter validation, observation filtering, and shared infrastructure.

## Context

Odigos has 2 API-calling tools (image_gen, music_gen) that each hand-roll HTTP clients, polling loops, parameter parsing, and error handling. As more API tools are added, this duplication compounds. The existing tool architecture spec (2026-04-03) proposed an `APIToolMixin` — this design refines that into a cleaner subclass approach with three additional capabilities: shared HTTP client, executor-level parameter validation, and per-tool observation filtering.

## Decisions

| Question | Decision | Rationale |
|----------|----------|-----------|
| HTTP client strategy | Single shared `httpx.AsyncClient` on Container | `httpx` handles per-host connection pooling internally. Simple, no per-tool client overhead. Swappable later without changing tool interface. |
| Parameter validation | Type coercion + schema validation via `jsonschema` in executor | Catches hallucinated params in 1ms vs 1s API roundtrip. Uses existing `parameters_schema` on every tool. No extra model classes needed. |
| Observation filtering | `format_for_context()` method on `BaseTool` | Tool knows its own output best. Default pass-through means zero change for existing tools. Global filters can layer on top in executor later. |
| Inheritance model | `APITool(BaseTool)` and `CLITool(BaseTool)` subclasses, not mixins | Clean single-inheritance chain. Avoids MRO issues. Maps to natural tool taxonomy: BaseTool > APITool, BaseTool > CLITool. |
| CLI tool design | First-class `CLITool` base with subprocess execution, input hardening, JSON-first output, mandatory distillation | CLI-as-tool-interface is an active pattern (mcp2cli, CLI-Anything, Google Workspace CLI). More token-efficient than MCP. Ready for immediate use when first CLI tool is needed. |

## Design

### 1. APITool Base Class

**New file:** `odigos/tools/api_tool.py`

```python
class ToolAPIError(Exception):
    """Raised when an external API returns an error."""
    def __init__(self, status_code: int, message: str,
                 failure_category: str = "unknown"):
        self.status_code = status_code
        self.message = message
        self.failure_category = failure_category  # transient, input, permission, unavailable, unknown

class APITool(BaseTool):
    """Base class for tools that call external HTTP APIs."""

    API_DOCS: str = ""  # URL to API docs for maintainers

    def __init__(self, http: httpx.AsyncClient, **kwargs):
        self._http = http

    @property
    def http(self) -> httpx.AsyncClient:
        return self._http

    async def api_post(self, url, payload, api_key, **kwargs) -> dict:
        """POST JSON with Bearer auth. Raises ToolAPIError on 4xx/5xx."""
        resp = await self.http.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            **kwargs,
        )
        data = resp.json()
        if resp.status_code >= 400:
            raise ToolAPIError(resp.status_code, data.get("msg") or data.get("error", "Unknown"))
        return data

    async def api_get(self, url, api_key, params=None, **kwargs) -> dict:
        """GET with Bearer auth. Raises ToolAPIError on 4xx/5xx."""
        resp = await self.http.get(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            params=params,
            **kwargs,
        )
        data = resp.json()
        if resp.status_code >= 400:
            raise ToolAPIError(resp.status_code, data.get("msg") or data.get("error", "Unknown"))
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
        """Poll an API endpoint with exponential backoff.
        Returns extracted result on success, raises ToolAPIError on failure/timeout."""
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

### 2. Observation Filtering on BaseTool

**Modified file:** `odigos/tools/base.py`

Add to `BaseTool`:

```python
def format_for_context(self, result: ToolResult) -> str:
    """Format tool output for the LLM context window.
    Override to summarize verbose output. Default: return data as-is."""
    return result.data
```

This is a non-abstract method with a pass-through default. Existing tools are unaffected. API tools override it to return concise summaries (e.g., "Generated image: sunset.png (1024x1024)" instead of raw JSON).

**Auto-distill fallback:** If a tool does not override `format_for_context()` and `result.data` exceeds 2000 characters, the executor applies a head-tail heuristic: keep the first 500 chars, the last 500 chars, and any lines in the middle containing signal words (error, exception, fail, warning, traceback). This prevents context rot from verbose tools without requiring every tool developer to implement summarization.

### 3. Parameter Validation in Executor

**Modified file:** `odigos/core/executor.py`

New function:

```python
import jsonschema

def _coerce_and_validate(params: dict, schema: dict) -> dict:
    """Coerce LLM string params to schema types, then validate constraints."""
    properties = schema.get("properties", {})
    coerced = dict(params)

    # Phase 1: Type coercion (LLM sends strings for everything)
    for key, spec in properties.items():
        if key not in coerced:
            continue
        val = coerced[key]
        if spec.get("type") == "boolean":
            coerced[key] = str(val).lower() == "true"
        elif spec.get("type") == "integer":
            try:
                coerced[key] = int(val)
            except (ValueError, TypeError):
                pass  # validation will catch it
        elif spec.get("type") == "number":
            try:
                coerced[key] = float(val)
            except (ValueError, TypeError):
                pass

    # Phase 2: Full schema validation (enums, required, maxLength, etc.)
    jsonschema.validate(coerced, schema)
    return coerced
```

Integration in `_execute_tool`, before `tool.execute(args)`:

```python
# Strip internal params before validation
internal = {k: args.pop(k) for k in list(args) if k.startswith("_")}
try:
    args = _coerce_and_validate(args, tool.parameters_schema)
except jsonschema.ValidationError as e:
    return ToolResult(
        success=False, data="",
        error=f"Invalid parameters: {e.message}",
        failure_category="input",
    )
args.update(internal)  # re-inject _conversation_id, _goal_id
```

Integration after result, before returning to LLM:

```python
display = tool.format_for_context(result)

# Auto-distill fallback: if tool didn't override and output is large
if display == result.data and len(display) > 2000:
    display = _auto_distill(display)

def _auto_distill(text: str) -> str:
    """Head-tail with signal extraction for verbose output."""
    signal_words = {"error", "exception", "fail", "warning", "traceback", "exit"}
    lines = text.splitlines()
    head = "\n".join(lines[:15])
    tail = "\n".join(lines[-15:])
    middle_signals = [
        l for l in lines[15:-15]
        if any(w in l.lower() for w in signal_words)
    ]
    mid = "\n".join(middle_signals[:10]) if middle_signals else "[...truncated...]"
    return f"{head}\n\n{mid}\n\n{tail}"
```

Error category mapping for `ToolAPIError`:

```python
except ToolAPIError as e:
    # Use the category from the exception directly, fall back to classifier
    category = e.failure_category if e.failure_category != "unknown" else classify(str(e))
    return ToolResult(success=False, data="", error=e.message, failure_category=category)
```

### 4. Shared HTTP Client on Container

**Modified file:** `odigos/container.py`

```python
@dataclass
class Container:
    # ... existing fields ...
    http_client: httpx.AsyncClient | None = None
```

**Modified file:** `odigos/bootstrap.py`

Creation in Phase 1 (before tool registration):

```python
container.http_client = httpx.AsyncClient(
    timeout=30,
    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
)
```

Shutdown (reverse order cleanup):

```python
if container.http_client:
    await container.http_client.aclose()
```

Passed to API tools during registration:

```python
registry.register(GenerateImageTool(
    http=container.http_client,
    api_key=kie_api_key,
    # ... rest of config ...
))
```

### 5. CLITool Base Class

**New file:** `odigos/tools/cli_tool.py`

CLI-as-tool-interface is an emerging pattern (mcp2cli, CLI-Anything, Google Workspace CLI, opencli) where agent capabilities are exposed as structured CLI commands rather than API calls or MCP schemas. This is more token-efficient than MCP (no schema retransmission per turn) and maps naturally to how agents already invoke tools.

References:
- https://justin.poehnelt.com/posts/rewrite-your-cli-for-ai-agents/
- https://github.com/knowsuchagency/mcp2cli
- https://github.com/HKUDS/CLI-Anything

```python
class CLIToolError(Exception):
    """Raised when a CLI tool execution fails."""
    def __init__(self, exit_code: int, stderr: str,
                 failure_category: str = "unknown"):
        self.exit_code = exit_code
        self.stderr = stderr
        self.failure_category = failure_category

class CLITool(BaseTool):
    """Base class for tools that execute CLI commands in a subprocess."""

    COMMAND: str = ""           # base command (e.g., "gws", "opencli")
    SANDBOX: str = "subprocess" # "subprocess" | "docker" | "bubblewrap"
    SKILL_FILE: str = ""        # path to SKILL.md for agent discoverability

    def __init__(self, working_dir: str = "", timeout: float = 60.0,
                 allowed_paths: list[str] | None = None):
        self._working_dir = working_dir
        self._timeout = timeout
        self._allowed_paths = allowed_paths or []

    async def run_cli(
        self,
        args: list[str],
        stdin: str | None = None,
        timeout: float | None = None,
        env: dict[str, str] | None = None,
    ) -> CLIResult:
        """Execute a CLI command in a sandboxed subprocess.
        Returns CLIResult with stdout, stderr, exit_code."""
        timeout = timeout or self._timeout
        cmd = [self.COMMAND] + args

        # Input hardening: reject path traversal, control chars
        for arg in args:
            _validate_cli_arg(arg)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE if stdin else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._working_dir or None,
            env={**os.environ, **(env or {})},
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(stdin.encode() if stdin else None),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            raise CLIToolError(-1, f"Timed out after {timeout}s", "transient")

        return CLIResult(
            exit_code=proc.returncode,
            stdout=stdout.decode(errors="replace"),
            stderr=stderr.decode(errors="replace"),
        )

    async def run_json(self, args: list[str], **kwargs) -> dict:
        """Run a CLI command and parse JSON output.
        Appends --output json if not present."""
        if "--output" not in args and "-o" not in args:
            args = args + ["--output", "json"]
        result = await self.run_cli(args, **kwargs)
        if result.exit_code != 0:
            raise CLIToolError(result.exit_code, result.stderr,
                             _classify_cli_error(result))
        return json.loads(result.stdout)

    def format_for_context(self, result: ToolResult) -> str:
        """CLI tools MUST override this — raw CLI output is always too verbose.
        Default applies auto-distill."""
        return _auto_distill(result.data) if len(result.data) > 2000 else result.data


@dataclass
class CLIResult:
    exit_code: int
    stdout: str
    stderr: str


def _validate_cli_arg(arg: str) -> None:
    """Reject dangerous CLI arguments. Agents hallucinate."""
    if ".." in arg and ("/" in arg or "\\" in arg):
        raise CLIToolError(-1, f"Path traversal rejected: {arg}", "input")
    if any(c in arg for c in ("\x00", "\r", "\n", "`", "$(")):
        raise CLIToolError(-1, f"Dangerous characters in argument: {arg!r}", "input")


def _classify_cli_error(result: CLIResult) -> str:
    """Map CLI exit codes and stderr to failure categories."""
    if result.exit_code == 126 or result.exit_code == 127:
        return "unavailable"  # command not found / not executable
    if result.exit_code == 1 and "permission" in result.stderr.lower():
        return "permission"
    if "timeout" in result.stderr.lower() or "timed out" in result.stderr.lower():
        return "transient"
    return "unknown"
```

Design principles:
- **JSON-first output:** `run_json()` appends `--output json` automatically, matching the pattern all modern agent CLIs converge on
- **Input hardening:** `_validate_cli_arg()` rejects path traversal and shell injection before execution — agents hallucinate, validate everything
- **Mandatory distillation:** Unlike APITool where the default is pass-through, CLITool's `format_for_context()` defaults to auto-distill because CLI output is inherently verbose
- **Failure classification:** Exit codes map to the same `failure_category` taxonomy as APITool, so the executor's retry logic works identically
- **Sandbox-ready:** `SANDBOX` class attribute declares execution strategy. Phase 1 implements `"subprocess"` only; `"docker"` and `"bubblewrap"` are future values that change the execution path in `run_cli()` without changing the tool interface
- **No dry-run yet:** `--dry-run` support is valuable but tool-specific. Individual CLITool subclasses can add it; the base class doesn't enforce it

Example future tool:

```python
class GoogleWorkspaceTool(CLITool):
    name = "google_workspace"
    COMMAND = "gws"
    SKILL_FILE = "skills/gws.md"
    category = CATEGORY_PRODUCTIVITY
    parameters_schema = {
        "type": "object",
        "properties": {
            "service": {"type": "string", "enum": ["drive", "sheets", "docs"]},
            "action": {"type": "string"},
            "args": {"type": "string", "description": "JSON payload for the action"},
        },
        "required": ["service", "action"],
    }

    async def execute(self, params: dict) -> ToolResult:
        try:
            data = await self.run_json([params["service"], params["action"],
                                        "--json", params.get("args", "{}")])
            return ToolResult(success=True, data=json.dumps(data))
        except CLIToolError as e:
            return ToolResult(success=False, data="", error=e.stderr,
                            failure_category=e.failure_category)

    def format_for_context(self, result: ToolResult) -> str:
        # Summarize: "Drive: listed 12 files in /Reports"
        ...
```

### 6. Tool Migration: image_gen

**Modified file:** `odigos/tools/image_gen.py`

Changes:
- Base class: `BaseTool` -> `APITool`
- Constructor: accepts `http` param, passes to `super().__init__(http=http)`
- `_create_task()`: replaces `async with httpx.AsyncClient()` with `self.api_post()`
- `_poll_result()`: replaces hand-rolled loop with `self.poll_until()`
- Manual boolean parsing removed (executor handles coercion)
- New `format_for_context()`: returns "Generated image: {filename} ({dimensions})" instead of raw API data

Unchanged:
- `_download_image()` — tool-specific file I/O
- Database artifact insertion — tool-specific schema
- `_conversation_id` extraction — needed for DB records
- `side_effect` format — unchanged

### 7. Tool Migration: music_gen

**Modified file:** `odigos/tools/music_gen.py`

Same pattern as image_gen:
- Base class: `BaseTool` -> `APITool`
- Constructor: accepts `http` param
- `_create_task()`: uses `self.api_post()`
- `_poll_result()`: uses `self.poll_until()` with callbacks for SUCCESS/failure states
- `_extract_tracks()`: unchanged (tool-specific response parsing)
- New `format_for_context()`: returns "Generated {n} tracks: {titles}" summary

### 8. Dependency

**Modified file:** `pyproject.toml`

```
"jsonschema>=4.0"
```

## Type Hierarchy

```
BaseTool (abstract)
  - format_for_context() [default: pass-through, auto-distill fallback in executor]
  - execute() [abstract]
  │
  ├── APITool(BaseTool)
  │     - http (shared AsyncClient)
  │     - api_post(), api_get(), poll_until()
  │     - ToolAPIError (with failure_category)
  │     │
  │     ├── GenerateImageTool(APITool)
  │     └── GenerateMusicTool(APITool)
  │
  ├── CLITool(BaseTool)
  │     - run_cli(), run_json()
  │     - CLIToolError (with failure_category)
  │     - Input hardening (_validate_cli_arg)
  │     - format_for_context() [default: auto-distill]
  │     - SANDBOX attribute ("subprocess" | "docker" | "bubblewrap")
  │
  └── Local tools (direct BaseTool subclasses)
        - CodeTool, FileTool, NotebookTool, etc.
```

## File Change Summary

| File | Change |
|------|--------|
| `odigos/tools/api_tool.py` | **New** — `APITool`, `ToolAPIError` |
| `odigos/tools/cli_tool.py` | **New** — `CLITool`, `CLIToolError`, `CLIResult`, input hardening |
| `odigos/tools/base.py` | Add `format_for_context()` default method |
| `odigos/core/executor.py` | Add `_coerce_and_validate()`, call it + `format_for_context()` in `_execute_tool` |
| `odigos/container.py` | Add `http_client` field |
| `odigos/bootstrap.py` | Create shared client (Phase 1), pass to API tools (Phase 5), close on shutdown |
| `odigos/tools/image_gen.py` | Rebase onto `APITool` |
| `odigos/tools/music_gen.py` | Rebase onto `APITool` |
| `pyproject.toml` | Add `jsonschema>=4.0` |

## Forward Compatibility: Backgroundable Tasks

The `poll_until` method blocks the conversation turn for up to 3 minutes. A future phase (after heartbeat decomposition) will implement yield-and-notify: tools return `ToolResult(status="pending", task_id=...)`, the executor yields control, and the heartbeat loop handles polling in the background.

To prepare for this without implementing it now:
- `ToolResult` gains an optional `status` field (default `None`, future values: `"pending"`, `"complete"`)
- `ToolResult` gains an optional `task_id` field (default `None`)
- `poll_until` stays in `APITool` for Phase 1 — it works correctly, just not optimally
- No executor, heartbeat, or frontend changes needed yet

This ensures the interface is ready when Phase 2 decomposes the heartbeat.

## Implementation Notes

- **API response codes:** Some APIs (Kie.ai) return HTTP 200 with an error in the JSON body (`code != 200`). The `api_post`/`api_get` methods handle HTTP-level errors. Tools must still check API-level status in their `execute()` method and raise `ToolAPIError` for API-specific failures. This is intentional — API response formats vary too much to generalize.
- **jsonschema may already be transitive:** Check `uv pip list` before adding. If already present, pin to the existing version.
- **Download methods:** `_download_image` and `_download_audio` use the shared client for HTTP GETs but may need longer timeouts. Pass `timeout=httpx.Timeout(120)` as a kwarg to `self.http.get()` for large file downloads.

## What This Does NOT Change

- Tool registry (`registry.py`) — works with `BaseTool`, `APITool` is-a `BaseTool`
- Local tools (code, file, notebook, kanban, artifacts) — no API calls, stay as-is
- MCP bridge — already standardized
- Email/calendar tools — use IMAP/CalDAV libraries, not direct HTTP
- ToolResult format — two optional fields added (`status`, `task_id`) with `None` defaults; all existing code unaffected
- ToolContract format — unchanged
- Frontend — unchanged
- Tool discovery (`find_tools`) — unchanged
