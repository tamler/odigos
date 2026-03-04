# Phase 2a: Web Search Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Give Odigos the ability to search the web via SearXNG and synthesize answers from search results.

**Architecture:** LLM-based intent classification in the planner decides when to search. A tool registry + two-pass executor pattern runs the search tool and then calls the LLM with results in context. The SearXNG provider is a thin httpx client with basic auth.

**Tech Stack:** httpx (already installed), SearXNG JSON API, OpenRouter (cheap model for classification)

---

### Task 1: SearXNG Provider

**Files:**
- Create: `odigos/providers/searxng.py`
- Test: `tests/test_searxng.py`

**Context:** This follows the same pattern as `odigos/providers/openrouter.py` and `odigos/providers/embeddings.py` -- an httpx.AsyncClient wrapper. The SearXNG instance is at `https://search.uxrls.com` with HTTP basic auth. Credentials come from env vars.

**Step 1: Write the failing test**

Create `tests/test_searxng.py`:

```python
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from odigos.providers.searxng import SearchResult, SearxngProvider


class TestSearxngProvider:
    @pytest.fixture
    def provider(self):
        return SearxngProvider(
            url="https://search.example.com",
            username="testuser",
            password="testpass",
        )

    async def test_search_returns_results(self, provider):
        """Search returns a list of SearchResult from SearXNG JSON API."""
        mock_response = httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Python Docs",
                        "url": "https://docs.python.org",
                        "content": "Official Python documentation.",
                    },
                    {
                        "title": "Real Python",
                        "url": "https://realpython.com",
                        "content": "Python tutorials and articles.",
                    },
                ]
            },
        )
        provider._client = AsyncMock()
        provider._client.get = AsyncMock(return_value=mock_response)

        results = await provider.search("python documentation")

        assert len(results) == 2
        assert results[0].title == "Python Docs"
        assert results[0].url == "https://docs.python.org"
        assert results[0].snippet == "Official Python documentation."
        provider._client.get.assert_called_once()

    async def test_search_respects_num_results(self, provider):
        """Search limits results to num_results parameter."""
        mock_response = httpx.Response(
            200,
            json={
                "results": [
                    {"title": f"Result {i}", "url": f"https://example.com/{i}", "content": f"Snippet {i}"}
                    for i in range(10)
                ]
            },
        )
        provider._client = AsyncMock()
        provider._client.get = AsyncMock(return_value=mock_response)

        results = await provider.search("test", num_results=3)

        assert len(results) == 3

    async def test_search_returns_empty_on_error(self, provider):
        """Search returns empty list on HTTP error instead of raising."""
        mock_response = httpx.Response(500, text="Internal Server Error")
        provider._client = AsyncMock()
        provider._client.get = AsyncMock(return_value=mock_response)

        results = await provider.search("failing query")

        assert results == []

    async def test_search_returns_empty_on_network_error(self, provider):
        """Search returns empty list on network errors."""
        provider._client = AsyncMock()
        provider._client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

        results = await provider.search("failing query")

        assert results == []
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_searxng.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'odigos.providers.searxng'`

**Step 3: Write minimal implementation**

Create `odigos/providers/searxng.py`:

```python
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

SEARXNG_DEFAULT_CATEGORIES = "general"


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


class SearxngProvider:
    """SearXNG search API client with basic auth."""

    def __init__(
        self,
        url: str,
        username: str,
        password: str,
    ) -> None:
        self.url = url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=5.0),
            auth=httpx.BasicAuth(username, password),
        )

    async def search(
        self,
        query: str,
        num_results: int = 5,
        categories: str = SEARXNG_DEFAULT_CATEGORIES,
    ) -> list[SearchResult]:
        """Search SearXNG and return top results.

        Returns an empty list on any error (network, HTTP, parse).
        """
        try:
            response = await self._client.get(
                f"{self.url}/search",
                params={
                    "q": query,
                    "format": "json",
                    "categories": categories,
                },
            )

            if response.status_code != 200:
                logger.warning(
                    "SearXNG returned status %d: %s",
                    response.status_code,
                    response.text[:200],
                )
                return []

            data = response.json()
            results = []
            for item in data.get("results", [])[:num_results]:
                results.append(
                    SearchResult(
                        title=item.get("title", ""),
                        url=item.get("url", ""),
                        snippet=item.get("content", ""),
                    )
                )
            return results

        except Exception:
            logger.exception("SearXNG search failed for query: %s", query)
            return []

    async def close(self) -> None:
        await self._client.aclose()
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_searxng.py -v`
Expected: 4 PASSED

**Step 5: Commit**

```bash
git add odigos/providers/searxng.py tests/test_searxng.py
git commit -m "feat: add SearXNG search provider with basic auth"
```

---

### Task 2: Tool Base + Registry

**Files:**
- Create: `odigos/tools/__init__.py`
- Create: `odigos/tools/base.py`
- Create: `odigos/tools/registry.py`
- Test: `tests/test_tools.py`

**Context:** This establishes the tool pattern for all future tools. A `BaseTool` abstract class defines the interface, `ToolResult` holds results, and `ToolRegistry` is a simple dict-based lookup. Keep it minimal -- YAGNI.

**Step 1: Write the failing test**

Create `tests/test_tools.py`:

```python
import pytest

from odigos.tools.base import BaseTool, ToolResult
from odigos.tools.registry import ToolRegistry


class FakeTool(BaseTool):
    name = "fake_tool"
    description = "A tool for testing."

    async def execute(self, params: dict) -> ToolResult:
        return ToolResult(success=True, data=f"executed with {params}")


class TestToolResult:
    def test_success_result(self):
        result = ToolResult(success=True, data="hello")
        assert result.success is True
        assert result.data == "hello"
        assert result.error is None

    def test_error_result(self):
        result = ToolResult(success=False, data="", error="something broke")
        assert result.success is False
        assert result.error == "something broke"


class TestToolRegistry:
    def test_register_and_get(self):
        registry = ToolRegistry()
        tool = FakeTool()
        registry.register(tool)

        retrieved = registry.get("fake_tool")
        assert retrieved is tool

    def test_get_unknown_returns_none(self):
        registry = ToolRegistry()
        assert registry.get("nonexistent") is None

    def test_list_tools(self):
        registry = ToolRegistry()
        registry.register(FakeTool())

        tools = registry.list()
        assert len(tools) == 1
        assert tools[0].name == "fake_tool"

    async def test_execute_tool(self):
        tool = FakeTool()
        result = await tool.execute({"key": "value"})
        assert result.success is True
        assert "key" in result.data
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tools.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write minimal implementation**

Create `odigos/tools/__init__.py`:

```python
```

Create `odigos/tools/base.py`:

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ToolResult:
    success: bool
    data: str
    error: str | None = None


class BaseTool(ABC):
    name: str
    description: str

    @abstractmethod
    async def execute(self, params: dict) -> ToolResult:
        """Execute the tool with the given parameters."""
        ...
```

Create `odigos/tools/registry.py`:

```python
from __future__ import annotations

from odigos.tools.base import BaseTool


class ToolRegistry:
    """Simple dict-based tool registry."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def list(self) -> list[BaseTool]:
        return list(self._tools.values())
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_tools.py -v`
Expected: 5 PASSED

**Step 5: Commit**

```bash
git add odigos/tools/__init__.py odigos/tools/base.py odigos/tools/registry.py tests/test_tools.py
git commit -m "feat: add tool base class and registry"
```

---

### Task 3: Search Tool

**Files:**
- Create: `odigos/tools/search.py`
- Test: `tests/test_tools_search.py`

**Context:** Wraps the SearXNG provider (Task 1) as a `BaseTool` (Task 2). The execute method takes `{"query": "..."}` and returns formatted search results as a string for context injection.

**Step 1: Write the failing test**

Create `tests/test_tools_search.py`:

```python
from unittest.mock import AsyncMock

import pytest

from odigos.providers.searxng import SearchResult
from odigos.tools.search import SearchTool


class TestSearchTool:
    @pytest.fixture
    def mock_searxng(self):
        provider = AsyncMock()
        provider.search.return_value = [
            SearchResult(title="Python Docs", url="https://docs.python.org", snippet="Official Python documentation."),
            SearchResult(title="Real Python", url="https://realpython.com", snippet="Python tutorials."),
        ]
        return provider

    @pytest.fixture
    def tool(self, mock_searxng):
        return SearchTool(searxng=mock_searxng)

    async def test_tool_name(self, tool):
        assert tool.name == "web_search"

    async def test_execute_returns_formatted_results(self, tool, mock_searxng):
        result = await tool.execute({"query": "python docs"})

        assert result.success is True
        assert "Python Docs" in result.data
        assert "https://docs.python.org" in result.data
        assert "Official Python documentation." in result.data
        mock_searxng.search.assert_called_once_with("python docs")

    async def test_execute_missing_query(self, tool):
        result = await tool.execute({})

        assert result.success is False
        assert "query" in result.error.lower()

    async def test_execute_empty_results(self, tool, mock_searxng):
        mock_searxng.search.return_value = []

        result = await tool.execute({"query": "obscure query"})

        assert result.success is True
        assert "no results" in result.data.lower()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tools_search.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'odigos.tools.search'`

**Step 3: Write minimal implementation**

Create `odigos/tools/search.py`:

```python
from __future__ import annotations

from typing import TYPE_CHECKING

from odigos.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from odigos.providers.searxng import SearxngProvider


class SearchTool(BaseTool):
    """Web search tool backed by SearXNG."""

    name = "web_search"
    description = "Search the web for current information on any topic."

    def __init__(self, searxng: SearxngProvider) -> None:
        self.searxng = searxng

    async def execute(self, params: dict) -> ToolResult:
        query = params.get("query")
        if not query:
            return ToolResult(success=False, data="", error="Missing required parameter: query")

        results = await self.searxng.search(query)

        if not results:
            return ToolResult(success=True, data="No results found for this search.")

        lines = [f"## Web search results for: {query}\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. **{r.title}**")
            lines.append(f"   {r.url}")
            lines.append(f"   {r.snippet}\n")

        return ToolResult(success=True, data="\n".join(lines))
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_tools_search.py -v`
Expected: 4 PASSED

**Step 5: Commit**

```bash
git add odigos/tools/search.py tests/test_tools_search.py
git commit -m "feat: add web search tool wrapping SearXNG provider"
```

---

### Task 4: Config -- SearXNG Settings

**Files:**
- Modify: `odigos/config.py:37-48` (Settings class)
- Modify: `tests/conftest.py:28-45` (test_settings fixture)
- Test: `tests/test_config.py` (existing, add test)

**Context:** Add `SearxngConfig` with `url`, `username`, `password` fields. All from env vars. The existing `Settings` class uses `pydantic_settings.BaseSettings` which reads from `.env`. See `odigos/config.py` for the pattern.

**Step 1: Write the failing test**

Add to `tests/test_config.py`:

```python
def test_searxng_config_from_env(monkeypatch):
    """SearXNG config reads URL, username, password from env vars."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("SEARXNG_URL", "https://search.example.com")
    monkeypatch.setenv("SEARXNG_USERNAME", "nimda")
    monkeypatch.setenv("SEARXNG_PASSWORD", "secret123")

    from odigos.config import Settings

    settings = Settings()
    assert settings.searxng_url == "https://search.example.com"
    assert settings.searxng_username == "nimda"
    assert settings.searxng_password == "secret123"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py::test_searxng_config_from_env -v`
Expected: FAIL with `ValidationError` (field not found)

**Step 3: Write minimal implementation**

Modify `odigos/config.py`. Add these three fields to `Settings` (after `openrouter_api_key`):

```python
class Settings(BaseSettings):
    telegram_bot_token: str
    openrouter_api_key: str
    searxng_url: str = ""
    searxng_username: str = ""
    searxng_password: str = ""

    # ... rest unchanged
```

Also update `tests/conftest.py` `test_settings` fixture to include the new fields:

```python
@pytest.fixture
def test_settings(tmp_db_path: str) -> Settings:
    return Settings(
        telegram_bot_token="test-token",
        openrouter_api_key="test-key",
        searxng_url="https://search.example.com",
        searxng_username="testuser",
        searxng_password="testpass",
        # ... rest unchanged
    )
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py -v`
Expected: 3 PASSED (existing 2 + new 1)

**Step 5: Commit**

```bash
git add odigos/config.py tests/test_config.py tests/conftest.py
git commit -m "feat: add SearXNG config fields to Settings"
```

---

### Task 5: Planner Upgrade -- LLM Intent Classification

**Files:**
- Modify: `odigos/core/planner.py` (full rewrite)
- Test: `tests/test_core.py` (update TestPlanner class)

**Context:** The planner currently returns a hardcoded `Plan(action="respond")`. Upgrade it to call a cheap LLM model with an intent classification prompt. If the LLM says the user needs a web search, the planner returns `Plan(action="search", tool_params={"query": "..."})`. The planner needs a reference to the LLM provider.

The `Plan` dataclass gets a new `tool_params` field. The classification prompt asks the LLM to respond with a simple JSON structure.

**Step 1: Write the failing test**

Replace `TestPlanner` in `tests/test_core.py` with:

```python
class TestPlanner:
    @pytest.fixture
    def mock_classify_provider(self):
        provider = AsyncMock()
        return provider

    async def test_classify_as_respond(self, mock_classify_provider):
        """Planner returns respond when LLM says no search needed."""
        mock_classify_provider.complete.return_value = LLMResponse(
            content='{"action": "respond"}',
            model="test/model",
            tokens_in=10,
            tokens_out=5,
            cost_usd=0.0,
        )
        planner = Planner(provider=mock_classify_provider)
        plan = await planner.plan("Hello, how are you?")

        assert plan.action == "respond"
        assert plan.tool_params == {}

    async def test_classify_as_search(self, mock_classify_provider):
        """Planner returns search with query when LLM says search needed."""
        mock_classify_provider.complete.return_value = LLMResponse(
            content='{"action": "search", "query": "weather in NYC today"}',
            model="test/model",
            tokens_in=10,
            tokens_out=10,
            cost_usd=0.0,
        )
        planner = Planner(provider=mock_classify_provider)
        plan = await planner.plan("What's the weather in NYC?")

        assert plan.action == "search"
        assert plan.tool_params == {"query": "weather in NYC today"}

    async def test_fallback_to_respond_on_parse_error(self, mock_classify_provider):
        """Planner falls back to respond if LLM returns unparseable response."""
        mock_classify_provider.complete.return_value = LLMResponse(
            content="I'm not sure what you mean",
            model="test/model",
            tokens_in=10,
            tokens_out=10,
            cost_usd=0.0,
        )
        planner = Planner(provider=mock_classify_provider)
        plan = await planner.plan("something weird")

        assert plan.action == "respond"

    async def test_fallback_to_respond_on_provider_error(self, mock_classify_provider):
        """Planner falls back to respond if LLM call fails entirely."""
        mock_classify_provider.complete.side_effect = RuntimeError("API down")
        planner = Planner(provider=mock_classify_provider)
        plan = await planner.plan("search for something")

        assert plan.action == "respond"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_core.py::TestPlanner -v`
Expected: FAIL with `TypeError: Planner() takes no arguments`

**Step 3: Write minimal implementation**

Rewrite `odigos/core/planner.py`:

```python
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.providers.base import LLMProvider

logger = logging.getLogger(__name__)

CLASSIFY_PROMPT = """You are an intent classifier. Given the user's message, decide if the assistant needs to search the web to answer well.

Respond with ONLY a JSON object (no markdown, no explanation):
- If web search is needed: {"action": "search", "query": "<optimized search query>"}
- If no search is needed: {"action": "respond"}

Search IS needed for: current events, factual questions, looking things up, "find me", "what is", recent news, prices, weather, technical questions the assistant might not know.
Search is NOT needed for: greetings, personal questions, opinions, creative writing, math, conversation about things already discussed."""


@dataclass
class Plan:
    action: str  # "respond" or "search"
    requires_tools: bool = False
    tool_params: dict = field(default_factory=dict)


class Planner:
    """Decides what actions to take for a given message.

    Uses a cheap LLM call to classify intent and extract search queries.
    """

    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    async def plan(self, message_content: str) -> Plan:
        try:
            response = await self.provider.complete(
                [
                    {"role": "system", "content": CLASSIFY_PROMPT},
                    {"role": "user", "content": message_content},
                ],
                max_tokens=100,
                temperature=0.0,
            )
            result = json.loads(response.content.strip())
            action = result.get("action", "respond")

            if action == "search":
                query = result.get("query", message_content)
                return Plan(action="search", requires_tools=True, tool_params={"query": query})

            return Plan(action="respond")

        except (json.JSONDecodeError, KeyError, RuntimeError):
            logger.warning("Intent classification failed, falling back to respond")
            return Plan(action="respond")
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_core.py::TestPlanner -v`
Expected: 4 PASSED

**Step 5: Commit**

```bash
git add odigos/core/planner.py tests/test_core.py
git commit -m "feat: upgrade planner with LLM intent classification"
```

---

### Task 6: Prompt Builder -- Tool Results Section

**Files:**
- Modify: `odigos/personality/prompt_builder.py:11-38`
- Test: `tests/test_personality.py` (add test to TestPromptBuilder)

**Context:** The prompt builder composes the system prompt from sections. Add a new optional `tool_context` parameter that injects tool results between memory context and the entity extraction instruction. See `odigos/personality/prompt_builder.py` for the current structure.

**Step 1: Write the failing test**

Add to `TestPromptBuilder` in `tests/test_personality.py`:

```python
    def test_builds_prompt_with_tool_context(self):
        """Tool context is injected between memory and entity extraction."""
        from odigos.personality.loader import Personality

        personality = Personality()
        result = build_system_prompt(
            personality=personality,
            memory_context="## Relevant memories\n- User likes Python.",
            tool_context="## Web search results for: python 3.13\n\n1. **Python 3.13 Release**\n   https://python.org\n   New features in Python 3.13.\n",
        )

        # Tool context should appear in the prompt
        assert "Web search results" in result
        assert "python 3.13" in result
        # Memory should appear before tool context
        mem_pos = result.index("Relevant memories")
        tool_pos = result.index("Web search results")
        assert mem_pos < tool_pos
        # Entity extraction should appear after tool context
        entity_pos = result.index("<!--entities")
        assert tool_pos < entity_pos

    def test_builds_prompt_without_tool_context(self):
        """Prompt works fine without tool context (backward compatible)."""
        from odigos.personality.loader import Personality

        personality = Personality()
        result = build_system_prompt(personality=personality)

        assert "Odigos" in result
        assert "<!--entities" in result
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_personality.py::TestPromptBuilder::test_builds_prompt_with_tool_context -v`
Expected: FAIL with `TypeError: build_system_prompt() got an unexpected keyword argument 'tool_context'`

**Step 3: Write minimal implementation**

Modify `build_system_prompt` in `odigos/personality/prompt_builder.py` to accept `tool_context`:

```python
def build_system_prompt(
    personality: Personality,
    memory_context: str = "",
    tool_context: str = "",
) -> str:
    """Compose the system prompt from structured sections.

    Sections:
    1. Identity -- who the agent is
    2. Voice guidelines -- how to communicate
    3. Memory context -- relevant memories (if any)
    4. Tool context -- results from tool execution (if any)
    5. Entity extraction -- always appended
    """
    sections = []

    # 1. Identity
    sections.append(_build_identity_section(personality))

    # 2. Voice guidelines
    sections.append(_build_voice_section(personality))

    # 3. Memory context (optional)
    if memory_context:
        sections.append(memory_context)

    # 4. Tool context (optional)
    if tool_context:
        sections.append(tool_context)

    # 5. Entity extraction (always)
    sections.append(ENTITY_EXTRACTION_INSTRUCTION)

    return "\n\n".join(sections)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_personality.py -v`
Expected: All tests PASSED (existing 5 + new 2 = 7)

**Step 5: Commit**

```bash
git add odigos/personality/prompt_builder.py tests/test_personality.py
git commit -m "feat: add tool_context section to prompt builder"
```

---

### Task 7: Context Assembler -- Tool Context Support

**Files:**
- Modify: `odigos/core/context.py:30-64`
- Test: `tests/test_core.py` (add test to TestContextAssembler)

**Context:** The context assembler's `build()` method needs to accept an optional `tool_context` string and pass it through to `build_system_prompt()`. See `odigos/core/context.py:30-46` for the current build method.

**Step 1: Write the failing test**

Add to `TestContextAssembler` in `tests/test_core.py`:

```python
    async def test_includes_tool_context(self, db: Database):
        assembler = ContextAssembler(
            db=db,
            agent_name="TestBot",
            history_limit=20,
            personality_path="/nonexistent",
        )

        messages = await assembler.build(
            "conv-1",
            "What is Python 3.13?",
            tool_context="## Web search results\n1. Python 3.13 release notes.",
        )

        system_content = messages[0]["content"]
        assert "Web search results" in system_content
        assert "Python 3.13 release notes" in system_content
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_core.py::TestContextAssembler::test_includes_tool_context -v`
Expected: FAIL with `TypeError: build() got an unexpected keyword argument 'tool_context'`

**Step 3: Write minimal implementation**

Modify `ContextAssembler.build()` in `odigos/core/context.py` to accept and pass through `tool_context`:

```python
    async def build(
        self, conversation_id: str, current_message: str, tool_context: str = ""
    ) -> list[dict]:
        """Assemble the full messages list: system + history + current."""
        messages: list[dict] = []

        # Load personality (hot reload -- re-read on every call)
        personality = load_personality(self.personality_path)

        # Get memory context if available
        memory_context = ""
        if self.memory_manager:
            memory_context = await self.memory_manager.recall(current_message)

        # Build system prompt via structured prompt builder
        system_prompt = build_system_prompt(
            personality=personality,
            memory_context=memory_context,
            tool_context=tool_context,
        )

        messages.append({"role": "system", "content": system_prompt})

        # Conversation history
        history = await self.db.fetch_all(
            "SELECT role, content FROM messages "
            "WHERE conversation_id = ? "
            "ORDER BY timestamp ASC "
            "LIMIT ?",
            (conversation_id, self.history_limit),
        )
        for row in history:
            messages.append({"role": row["role"], "content": row["content"]})

        # Current message
        messages.append({"role": "user", "content": current_message})

        return messages
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_core.py::TestContextAssembler -v`
Expected: All 3 tests PASSED

**Step 5: Commit**

```bash
git add odigos/core/context.py tests/test_core.py
git commit -m "feat: add tool_context parameter to context assembler"
```

---

### Task 8: Executor Upgrade -- Two-Pass Tool Execution

**Files:**
- Modify: `odigos/core/executor.py` (full rewrite)
- Test: `tests/test_core.py` (update TestExecutor class)

**Context:** The executor currently just calls the LLM. Upgrade it to accept a `Plan` and a `ToolRegistry`. When the plan says "search", look up the tool, execute it, then call the LLM with results in context. The two-pass pattern: tool first, then LLM with tool results.

See `odigos/core/executor.py` for the current code and `odigos/core/planner.py` (Task 5) for the Plan dataclass.

**Step 1: Write the failing test**

Replace `TestExecutor` in `tests/test_core.py` with:

```python
from odigos.core.planner import Plan
from odigos.tools.base import ToolResult
from odigos.tools.registry import ToolRegistry


class TestExecutor:
    async def test_execute_respond(self, db: Database, mock_provider: AsyncMock):
        """Respond plan calls LLM directly without tools."""
        assembler = ContextAssembler(
            db=db, agent_name="TestBot", history_limit=20, personality_path="/nonexistent"
        )
        executor = Executor(provider=mock_provider, context_assembler=assembler)
        plan = Plan(action="respond")

        result = await executor.execute("conv-1", "Hello", plan=plan)

        assert result.content == "I'm Odigos, your assistant."
        mock_provider.complete.assert_called_once()

    async def test_execute_search(self, db: Database, mock_provider: AsyncMock):
        """Search plan calls tool then LLM with results in context."""
        mock_tool = AsyncMock()
        mock_tool.name = "web_search"
        mock_tool.execute.return_value = ToolResult(
            success=True, data="## Results\n1. Python docs"
        )

        registry = ToolRegistry()
        registry.register(mock_tool)

        assembler = ContextAssembler(
            db=db, agent_name="TestBot", history_limit=20, personality_path="/nonexistent"
        )
        executor = Executor(
            provider=mock_provider, context_assembler=assembler, tool_registry=registry
        )
        plan = Plan(action="search", requires_tools=True, tool_params={"query": "python docs"})

        result = await executor.execute("conv-1", "Find python docs", plan=plan)

        # Tool should have been called
        mock_tool.execute.assert_called_once_with({"query": "python docs"})
        # LLM should have been called with tool results in context
        mock_provider.complete.assert_called_once()
        call_messages = mock_provider.complete.call_args[0][0]
        system_content = call_messages[0]["content"]
        assert "Results" in system_content

    async def test_execute_search_tool_failure(self, db: Database, mock_provider: AsyncMock):
        """Search falls back to normal response if tool fails."""
        mock_tool = AsyncMock()
        mock_tool.name = "web_search"
        mock_tool.execute.return_value = ToolResult(
            success=False, data="", error="Connection refused"
        )

        registry = ToolRegistry()
        registry.register(mock_tool)

        assembler = ContextAssembler(
            db=db, agent_name="TestBot", history_limit=20, personality_path="/nonexistent"
        )
        executor = Executor(
            provider=mock_provider, context_assembler=assembler, tool_registry=registry
        )
        plan = Plan(action="search", requires_tools=True, tool_params={"query": "test"})

        result = await executor.execute("conv-1", "search for test", plan=plan)

        # Should still get a response (LLM called without tool results)
        assert result.content == "I'm Odigos, your assistant."

    async def test_backward_compat_no_plan(self, db: Database, mock_provider: AsyncMock):
        """Executor works without plan (backward compat, defaults to respond)."""
        assembler = ContextAssembler(
            db=db, agent_name="TestBot", history_limit=20, personality_path="/nonexistent"
        )
        executor = Executor(provider=mock_provider, context_assembler=assembler)

        result = await executor.execute("conv-1", "Hello")

        assert result.content == "I'm Odigos, your assistant."
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_core.py::TestExecutor -v`
Expected: FAIL (new test signatures don't match current Executor)

**Step 3: Write minimal implementation**

Rewrite `odigos/core/executor.py`:

```python
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from odigos.core.context import ContextAssembler
from odigos.core.planner import Plan
from odigos.providers.base import LLMProvider, LLMResponse

if TYPE_CHECKING:
    from odigos.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class Executor:
    """Runs the plan -- calls tools then LLM with results in context.

    Two-pass pattern:
    1. If plan requires tools, execute the tool and get results
    2. Call LLM with tool results injected into the system prompt
    """

    def __init__(
        self,
        provider: LLMProvider,
        context_assembler: ContextAssembler,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self.provider = provider
        self.context_assembler = context_assembler
        self.tool_registry = tool_registry

    async def execute(
        self,
        conversation_id: str,
        message_content: str,
        plan: Plan | None = None,
    ) -> LLMResponse:
        if plan is None:
            plan = Plan(action="respond")

        tool_context = ""

        # If plan requires a tool, execute it
        if plan.action == "search" and self.tool_registry:
            tool = self.tool_registry.get("web_search")
            if tool:
                try:
                    result = await tool.execute(plan.tool_params)
                    if result.success:
                        tool_context = result.data
                    else:
                        logger.warning("Tool web_search failed: %s", result.error)
                except Exception:
                    logger.exception("Tool web_search raised an exception")

        messages = await self.context_assembler.build(
            conversation_id, message_content, tool_context=tool_context
        )
        return await self.provider.complete(messages)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_core.py::TestExecutor -v`
Expected: 4 PASSED

**Step 5: Commit**

```bash
git add odigos/core/executor.py tests/test_core.py
git commit -m "feat: upgrade executor with two-pass tool execution"
```

---

### Task 9: Agent Wiring -- Connect Planner + Executor + Registry

**Files:**
- Modify: `odigos/core/agent.py:17-64`
- Modify: `odigos/main.py:32-107`
- Test: `tests/test_core.py` (update TestAgent and TestAgentWithMemory)

**Context:** The agent needs to:
1. Accept a `tool_registry` and pass it to the executor
2. Accept a `planner_provider` (for the cheap LLM classification call) and pass it to the planner
3. Pass the planner's `Plan` to the executor's `execute()` method

`main.py` needs to:
1. Initialize SearXNG provider (from env vars)
2. Create SearchTool and register it
3. Pass tool registry to Agent
4. Clean up SearXNG provider on shutdown

**Step 1: Write the failing test**

Update `TestAgent` and `TestAgentWithMemory` in `tests/test_core.py`:

```python
class TestAgentWithMemory:
    async def test_full_loop_with_memory(self, db: Database, mock_provider: AsyncMock):
        """Agent passes user_message to reflector when memory is wired."""
        mock_memory = AsyncMock()
        mock_memory.recall.return_value = ""

        # Planner provider: returns "respond" intent
        mock_planner_provider = AsyncMock()
        mock_planner_provider.complete.return_value = LLMResponse(
            content='{"action": "respond"}',
            model="test/model",
            tokens_in=5,
            tokens_out=5,
            cost_usd=0.0,
        )

        agent = Agent(
            db=db,
            provider=mock_provider,
            agent_name="TestBot",
            history_limit=20,
            memory_manager=mock_memory,
            personality_path="/nonexistent",
            planner_provider=mock_planner_provider,
        )
        message = _make_message("Hello agent")

        response = await agent.handle_message(message)
        assert response == "I'm Odigos, your assistant."

        # Verify memory_manager.store was called (via reflector)
        mock_memory.store.assert_called_once()


class TestAgent:
    async def test_full_loop(self, db: Database, mock_provider: AsyncMock):
        # Planner provider: returns "respond" intent
        mock_planner_provider = AsyncMock()
        mock_planner_provider.complete.return_value = LLMResponse(
            content='{"action": "respond"}',
            model="test/model",
            tokens_in=5,
            tokens_out=5,
            cost_usd=0.0,
        )

        agent = Agent(
            db=db,
            provider=mock_provider,
            agent_name="TestBot",
            history_limit=20,
            personality_path="/nonexistent",
            planner_provider=mock_planner_provider,
        )
        message = _make_message("Hello agent")

        response = await agent.handle_message(message)

        assert response == "I'm Odigos, your assistant."

        # Verify conversation was created
        conv = await db.fetch_one("SELECT * FROM conversations LIMIT 1")
        assert conv is not None
        assert conv["channel"] == "telegram"

        # Verify messages stored (user + assistant)
        msgs = await db.fetch_all("SELECT role FROM messages ORDER BY timestamp")
        roles = [m["role"] for m in msgs]
        assert "user" in roles
        assert "assistant" in roles

    async def test_search_flow(self, db: Database, mock_provider: AsyncMock):
        """Agent performs search when planner classifies as search intent."""
        # Planner says: search
        mock_planner_provider = AsyncMock()
        mock_planner_provider.complete.return_value = LLMResponse(
            content='{"action": "search", "query": "python 3.13 features"}',
            model="test/model",
            tokens_in=5,
            tokens_out=10,
            cost_usd=0.0,
        )

        # Search tool mock
        mock_tool = AsyncMock()
        mock_tool.name = "web_search"
        mock_tool.execute.return_value = ToolResult(
            success=True, data="## Results\n1. Python 3.13 released"
        )

        registry = ToolRegistry()
        registry.register(mock_tool)

        agent = Agent(
            db=db,
            provider=mock_provider,
            agent_name="TestBot",
            history_limit=20,
            personality_path="/nonexistent",
            planner_provider=mock_planner_provider,
            tool_registry=registry,
        )
        message = _make_message("What's new in Python 3.13?")

        response = await agent.handle_message(message)
        assert response == "I'm Odigos, your assistant."

        # Tool should have been called
        mock_tool.execute.assert_called_once()
```

Note: You'll need to add these imports at the top of `tests/test_core.py`:

```python
from odigos.tools.base import ToolResult
from odigos.tools.registry import ToolRegistry
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_core.py::TestAgent -v`
Expected: FAIL with `TypeError: Agent.__init__() got an unexpected keyword argument 'planner_provider'`

**Step 3: Write minimal implementation**

Update `odigos/core/agent.py`:

```python
from __future__ import annotations

from typing import TYPE_CHECKING

from odigos.channels.base import UniversalMessage
from odigos.core.context import ContextAssembler
from odigos.core.executor import Executor
from odigos.core.planner import Planner
from odigos.core.reflector import Reflector
from odigos.db import Database
from odigos.providers.base import LLMProvider

if TYPE_CHECKING:
    from odigos.memory.manager import MemoryManager
    from odigos.tools.registry import ToolRegistry


class Agent:
    """Main agent: receives messages, runs plan->execute->reflect loop."""

    def __init__(
        self,
        db: Database,
        provider: LLMProvider,
        agent_name: str = "Odigos",
        history_limit: int = 20,
        memory_manager: MemoryManager | None = None,
        personality_path: str = "data/personality.yaml",
        planner_provider: LLMProvider | None = None,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self.db = db
        self.planner = Planner(provider=planner_provider or provider)
        self.context_assembler = ContextAssembler(
            db,
            agent_name,
            history_limit,
            memory_manager=memory_manager,
            personality_path=personality_path,
        )
        self.executor = Executor(
            provider, self.context_assembler, tool_registry=tool_registry
        )
        self.reflector = Reflector(db, memory_manager=memory_manager)

    async def handle_message(self, message: UniversalMessage) -> str:
        """Process an incoming message and return a response string."""
        # Find or create conversation
        conversation_id = await self._get_or_create_conversation(message)

        # Store user message
        await self.db.execute(
            "INSERT INTO messages (id, conversation_id, role, content) VALUES (?, ?, ?, ?)",
            (message.id, conversation_id, "user", message.content),
        )

        # Plan -> Execute -> Reflect
        plan = await self.planner.plan(message.content)
        response = await self.executor.execute(
            conversation_id, message.content, plan=plan
        )
        await self.reflector.reflect(
            conversation_id, response, user_message=message.content
        )

        # Update conversation
        await self.db.execute(
            "UPDATE conversations SET last_message_at = datetime('now'), "
            "message_count = message_count + 2 WHERE id = ?",
            (conversation_id,),
        )

        return response.content

    async def _get_or_create_conversation(self, message: UniversalMessage) -> str:
        """Get existing conversation for this chat, or create a new one."""
        chat_id = message.metadata.get("chat_id", message.sender)
        lookup_id = f"{message.channel}:{chat_id}"

        existing = await self.db.fetch_one(
            "SELECT id FROM conversations WHERE id = ?", (lookup_id,)
        )
        if existing:
            return existing["id"]

        await self.db.execute(
            "INSERT INTO conversations (id, channel) VALUES (?, ?)",
            (lookup_id, message.channel),
        )
        return lookup_id
```

Update `odigos/main.py` -- add SearXNG provider, search tool, tool registry initialization. After the memory system init block and before the agent init block:

```python
    # Initialize search tools (if SearXNG is configured)
    _searxng = None
    tool_registry = None
    if settings.searxng_url:
        from odigos.providers.searxng import SearxngProvider
        from odigos.tools.registry import ToolRegistry
        from odigos.tools.search import SearchTool

        _searxng = SearxngProvider(
            url=settings.searxng_url,
            username=settings.searxng_username,
            password=settings.searxng_password,
        )
        search_tool = SearchTool(searxng=_searxng)
        tool_registry = ToolRegistry()
        tool_registry.register(search_tool)
        logger.info("Search tools initialized (SearXNG: %s)", settings.searxng_url)
```

Update the Agent initialization in `main.py` to pass the new params:

```python
    agent = Agent(
        db=_db,
        provider=_provider,
        agent_name=settings.agent.name,
        memory_manager=memory_manager,
        personality_path=settings.personality.path,
        planner_provider=_provider,  # same provider for now, swap to cheap model later
        tool_registry=tool_registry,
    )
```

Add `_searxng` to the module-level refs and cleanup:

```python
_searxng: SearxngProvider | None = None
```

Add to shutdown:
```python
    if _searxng:
        await _searxng.close()
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_core.py -v`
Expected: All tests PASSED

**Step 5: Commit**

```bash
git add odigos/core/agent.py odigos/main.py tests/test_core.py
git commit -m "feat: wire planner, executor, and tool registry into agent"
```

---

### Task 10: Final Verification + Lint

**Files:**
- No new files

**Context:** Run the full test suite, lint, format, and verify everything works together.

**Step 1: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests pass (62 existing + ~18 new = ~80 total)

**Step 2: Run lint**

Run: `uv run ruff check`
Expected: All checks passed

**Step 3: Run formatter**

Run: `uv run ruff format`
Expected: All files formatted

**Step 4: Re-run tests after formatting**

Run: `uv run pytest -v`
Expected: All tests still pass

**Step 5: Commit any lint/format fixes**

```bash
git add -A
git commit -m "chore: Phase 2a final lint, formatting, and verification"
```
