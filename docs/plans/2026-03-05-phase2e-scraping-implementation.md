# Phase 2e: Page Scraping Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add on-demand page scraping so the agent can fetch, read, and synthesize content from any URL.

**Architecture:** httpx (already installed) handles async HTTP fetching. Scrapling's `Adaptor` parses HTML and extracts clean text via CSS selectors. New `read_page` tool registered in the existing tool registry. Planner gets a `"scrape"` action. Reflector logs scrapes to a new `scraped_pages` table.

**Tech Stack:** scrapling (base parser), httpx (HTTP), aiosqlite (DB), pytest

---

### Task 1: Add scrapling dependency

**Files:**
- Modify: `pyproject.toml:6-15`

**Step 1: Add scrapling to dependencies**

In `pyproject.toml`, add `"scrapling>=0.3.0"` to the `dependencies` list (after `sqlite-vec`):

```toml
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.34.0",
    "httpx>=0.28.0",
    "aiosqlite>=0.20.0",
    "python-telegram-bot>=21.0",
    "pydantic-settings>=2.7.0",
    "pyyaml>=6.0",
    "sqlite-vec>=0.1.0",
    "scrapling>=0.3.0",
]
```

**Step 2: Install**

Run: `uv sync`
Expected: scrapling installed successfully.

**Step 3: Verify import**

Run: `uv run python -c "from scrapling import Adaptor; print('OK')"`
Expected: `OK`

**Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "deps: add scrapling for page content extraction"
```

---

### Task 2: Scraper provider

**Files:**
- Create: `odigos/providers/scraper.py`
- Create: `tests/test_scraper.py`

**Context:** The scraper provider is the low-level HTTP + parsing layer. It uses httpx (already in `odigos/providers/searxng.py` as a pattern) for async HTTP and Scrapling's `Adaptor` for HTML parsing. It does NOT depend on any tool or planner code.

Reference `odigos/providers/searxng.py` for the httpx.AsyncClient pattern (timeout, error handling, close method).

**Step 1: Write the failing tests**

Create `tests/test_scraper.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from odigos.providers.scraper import ScrapedPage, ScraperProvider


class TestScrapedPage:
    def test_dataclass_fields(self):
        page = ScrapedPage(url="https://example.com", title="Example", content="Hello world")
        assert page.url == "https://example.com"
        assert page.title == "Example"
        assert page.content == "Hello world"
        assert page.scraped_at is not None

    def test_default_scraped_at(self):
        page = ScrapedPage(url="https://example.com", title="", content="")
        assert isinstance(page.scraped_at, str)
        assert len(page.scraped_at) > 0


class TestScraperProvider:
    async def test_scrape_success(self):
        """Successful scrape returns ScrapedPage with extracted content."""
        html = "<html><head><title>Test Page</title></head><body><article><p>Main content here.</p></article></body></html>"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = html

        provider = ScraperProvider()
        with patch.object(provider._client, "get", new_callable=AsyncMock, return_value=mock_response):
            result = await provider.scrape("https://example.com")

        assert result.url == "https://example.com"
        assert result.title == "Test Page"
        assert "Main content" in result.content

    async def test_scrape_truncates_long_content(self):
        """Content longer than max_content_chars is truncated."""
        long_text = "word " * 2000  # ~10000 chars
        html = f"<html><head><title>Long</title></head><body><p>{long_text}</p></body></html>"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = html

        provider = ScraperProvider(max_content_chars=100)
        with patch.object(provider._client, "get", new_callable=AsyncMock, return_value=mock_response):
            result = await provider.scrape("https://example.com")

        assert len(result.content) <= 130  # 100 + truncation notice
        assert "[truncated]" in result.content

    async def test_scrape_http_error(self):
        """HTTP errors return ScrapedPage with empty content."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = Exception("Not Found")

        provider = ScraperProvider()
        with patch.object(provider._client, "get", new_callable=AsyncMock, return_value=mock_response):
            result = await provider.scrape("https://example.com/missing")

        assert result.url == "https://example.com/missing"
        assert result.content == ""

    async def test_scrape_network_error(self):
        """Network errors return ScrapedPage with empty content."""
        provider = ScraperProvider()
        with patch.object(provider._client, "get", new_callable=AsyncMock, side_effect=Exception("Connection refused")):
            result = await provider.scrape("https://unreachable.test")

        assert result.url == "https://unreachable.test"
        assert result.content == ""

    async def test_close(self):
        """Close shuts down the httpx client."""
        provider = ScraperProvider()
        with patch.object(provider._client, "aclose", new_callable=AsyncMock) as mock_close:
            await provider.close()
            mock_close.assert_called_once()
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_scraper.py -v`
Expected: FAIL (ModuleNotFoundError: No module named 'odigos.providers.scraper')

**Step 3: Write the implementation**

Create `odigos/providers/scraper.py`:

```python
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

# CSS selectors to try for main content, in priority order
_CONTENT_SELECTORS = [
    "article",
    "main",
    "[role='main']",
    ".post-content",
    ".entry-content",
    "#content",
]


@dataclass
class ScrapedPage:
    url: str
    title: str
    content: str
    scraped_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ScraperProvider:
    """Fetches web pages and extracts clean text content.

    Uses httpx for async HTTP and Scrapling's Adaptor for HTML parsing.
    """

    def __init__(self, max_content_chars: int = 4000) -> None:
        self.max_content_chars = max_content_chars
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=5.0),
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; Odigos/0.1)"},
        )

    async def scrape(self, url: str) -> ScrapedPage:
        try:
            response = await self._client.get(url)
            response.raise_for_status()
        except Exception:
            logger.warning("Failed to fetch %s", url, exc_info=True)
            return ScrapedPage(url=url, title="", content="")

        try:
            from scrapling import Adaptor

            page = Adaptor(response.text, url=url)

            title = ""
            title_el = page.css("title::text")
            if title_el:
                title = title_el.get(default="")

            # Try content-specific selectors first, fall back to body
            content_text = ""
            for selector in _CONTENT_SELECTORS:
                elements = page.css(selector)
                if elements:
                    content_text = elements.get_all_text(separator="\n", strip=True)
                    break

            if not content_text:
                body = page.css("body")
                if body:
                    content_text = body.get_all_text(separator="\n", strip=True)

            # Truncate if needed
            if len(content_text) > self.max_content_chars:
                content_text = content_text[: self.max_content_chars] + "\n\n[truncated]"

            return ScrapedPage(url=url, title=title, content=content_text)

        except Exception:
            logger.warning("Failed to parse content from %s", url, exc_info=True)
            return ScrapedPage(url=url, title="", content="")

    async def close(self) -> None:
        await self._client.aclose()
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_scraper.py -v`
Expected: 6 passed

Note: The `get_all_text` method is from Scrapling's Adaptor. If this method doesn't exist under that name, check the Scrapling docs and adjust to the correct API (e.g. `.text` property or `::text` pseudo-selector with `.getall()`). The test mocks the HTTP layer, but the HTML parsing uses real Scrapling -- if any parsing test fails, adjust the CSS selector/extraction logic to match Scrapling's actual API.

**Step 5: Commit**

```bash
git add odigos/providers/scraper.py tests/test_scraper.py
git commit -m "feat: add scraper provider with httpx + scrapling"
```

---

### Task 3: Scrape tool

**Files:**
- Create: `odigos/tools/scrape.py`
- Create: `tests/test_tools_scrape.py`

**Context:** This follows the exact same pattern as `odigos/tools/search.py` -- a `BaseTool` subclass wrapping a provider. Reference that file for structure.

**Step 1: Write the failing tests**

Create `tests/test_tools_scrape.py`:

```python
from unittest.mock import AsyncMock, patch

import pytest

from odigos.providers.scraper import ScrapedPage
from odigos.tools.scrape import ScrapeTool


class TestScrapeTool:
    def test_tool_metadata(self):
        mock_scraper = AsyncMock()
        tool = ScrapeTool(scraper=mock_scraper)
        assert tool.name == "read_page"
        assert "page" in tool.description.lower() or "read" in tool.description.lower()

    async def test_execute_success(self):
        mock_scraper = AsyncMock()
        mock_scraper.scrape.return_value = ScrapedPage(
            url="https://example.com",
            title="Example Page",
            content="This is the main content of the page.",
        )
        tool = ScrapeTool(scraper=mock_scraper)

        result = await tool.execute({"url": "https://example.com"})

        assert result.success is True
        assert "Example Page" in result.data
        assert "main content" in result.data
        mock_scraper.scrape.assert_called_once_with("https://example.com")

    async def test_execute_empty_content(self):
        mock_scraper = AsyncMock()
        mock_scraper.scrape.return_value = ScrapedPage(
            url="https://example.com/broken", title="", content=""
        )
        tool = ScrapeTool(scraper=mock_scraper)

        result = await tool.execute({"url": "https://example.com/broken"})

        assert result.success is True
        assert "could not extract" in result.data.lower() or "no content" in result.data.lower()

    async def test_execute_missing_url(self):
        mock_scraper = AsyncMock()
        tool = ScrapeTool(scraper=mock_scraper)

        result = await tool.execute({})

        assert result.success is False
        assert "url" in result.error.lower()
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools_scrape.py -v`
Expected: FAIL (ModuleNotFoundError: No module named 'odigos.tools.scrape')

**Step 3: Write the implementation**

Create `odigos/tools/scrape.py`:

```python
from __future__ import annotations

from typing import TYPE_CHECKING

from odigos.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from odigos.providers.scraper import ScraperProvider


class ScrapeTool(BaseTool):
    """Page scraping tool -- fetches and extracts content from a URL."""

    name = "read_page"
    description = "Read and extract content from a web page URL."

    def __init__(self, scraper: ScraperProvider) -> None:
        self.scraper = scraper

    async def execute(self, params: dict) -> ToolResult:
        url = params.get("url")
        if not url:
            return ToolResult(success=False, data="", error="Missing required parameter: url")

        page = await self.scraper.scrape(url)

        if not page.content:
            return ToolResult(
                success=True,
                data=f"Could not extract content from {url}.",
            )

        lines = [f"## Page: {page.title or page.url}\n"]
        lines.append(f"**URL:** {page.url}\n")
        lines.append(page.content)

        return ToolResult(success=True, data="\n".join(lines))
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_scrape.py -v`
Expected: 4 passed

**Step 5: Commit**

```bash
git add odigos/tools/scrape.py tests/test_tools_scrape.py
git commit -m "feat: add read_page scraping tool"
```

---

### Task 4: Database migration for scraped_pages table

**Files:**
- Create: `migrations/003_scraped_pages.sql`

**Step 1: Write the migration**

Create `migrations/003_scraped_pages.sql`:

```sql
CREATE TABLE IF NOT EXISTS scraped_pages (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    title TEXT,
    summary TEXT,
    scraped_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_scraped_pages_url ON scraped_pages(url);
CREATE INDEX IF NOT EXISTS idx_scraped_pages_scraped_at ON scraped_pages(scraped_at);
```

**Step 2: Verify migration runs**

Run: `uv run pytest tests/test_core.py::TestContextAssembler::test_builds_messages_list -v`
Expected: PASS (this test initializes the DB with migrations -- if it passes, the migration is valid SQL)

**Step 3: Commit**

```bash
git add migrations/003_scraped_pages.sql
git commit -m "feat: add scraped_pages table migration"
```

---

### Task 5: Planner upgrade -- add scrape action

**Files:**
- Modify: `odigos/core/planner.py:14-21` (CLASSIFY_PROMPT)
- Modify: `tests/test_core.py` (TestPlanner class)

**Context:** The planner currently classifies messages as `"respond"` or `"search"`. We add a third action: `"scrape"` with `tool_params: {"url": "..."}`. The planner extracts URLs from user messages when it detects scrape intent.

Reference `odigos/core/planner.py` for the current CLASSIFY_PROMPT and `_parse_json` helper.

**Step 1: Write the failing test**

Add to the `TestPlanner` class in `tests/test_core.py`:

```python
    async def test_classify_as_scrape(self, mock_classify_provider):
        """Planner returns scrape with URL when LLM detects page-reading intent."""
        mock_classify_provider.complete.return_value = LLMResponse(
            content='{"action": "scrape", "url": "https://example.com/article"}',
            model="test/model",
            tokens_in=10,
            tokens_out=10,
            cost_usd=0.0,
        )
        planner = Planner(provider=mock_classify_provider)
        plan = await planner.plan("Read this page: https://example.com/article")

        assert plan.action == "scrape"
        assert plan.tool_params == {"url": "https://example.com/article"}
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_core.py::TestPlanner::test_classify_as_scrape -v`
Expected: FAIL (assert plan.action == "scrape" -- currently planner doesn't handle "scrape")

**Step 3: Update the planner**

In `odigos/core/planner.py`, update the `CLASSIFY_PROMPT` to include scrape:

```python
CLASSIFY_PROMPT = """You are an intent classifier. Given the user's message, decide if the assistant needs to search the web or read a specific page to answer well.

Respond with ONLY a JSON object (no markdown, no explanation):
- If web search is needed: {"action": "search", "query": "<optimized search query>"}
- If reading a specific URL is needed: {"action": "scrape", "url": "<the URL>"}
- If no tools are needed: {"action": "respond"}

Search IS needed for: current events, factual questions, looking things up, "find me", "what is", recent news, prices, weather, technical questions the assistant might not know.
Scrape IS needed for: when the user shares a URL and wants to know what it says, "read this", "summarize this page", "what does this link say", any message containing a URL that the user wants analyzed.
Neither is needed for: greetings, personal questions, opinions, creative writing, math, conversation about things already discussed."""
```

In the `plan` method, add handling for the `"scrape"` action after the `"search"` block:

```python
            if action == "search":
                query = result.get("query", message_content)
                return Plan(action="search", requires_tools=True, tool_params={"query": query})

            if action == "scrape":
                url = result.get("url", "")
                if url:
                    return Plan(action="scrape", requires_tools=True, tool_params={"url": url})
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_core.py::TestPlanner -v`
Expected: 6 passed (5 existing + 1 new)

**Step 5: Commit**

```bash
git add odigos/core/planner.py tests/test_core.py
git commit -m "feat: planner recognizes scrape intent with URL extraction"
```

---

### Task 6: Executor upgrade -- handle scrape action

**Files:**
- Modify: `odigos/core/executor.py:46-56`
- Modify: `tests/test_core.py` (TestExecutor class)

**Context:** The executor currently handles `"search"` by looking up `"web_search"` from the tool registry. We add the same pattern for `"scrape"` looking up `"read_page"`. Reference `odigos/core/executor.py` for the current two-pass pattern.

**Step 1: Write the failing test**

Add to the `TestExecutor` class in `tests/test_core.py`:

```python
    async def test_execute_scrape(self, db: Database, mock_provider: AsyncMock):
        """Scrape plan calls read_page tool then LLM with page content in context."""
        mock_tool = AsyncMock()
        mock_tool.name = "read_page"
        mock_tool.execute.return_value = ToolResult(
            success=True, data="## Page: Example\n\nThe article content."
        )

        registry = ToolRegistry()
        registry.register(mock_tool)

        assembler = ContextAssembler(
            db=db, agent_name="TestBot", history_limit=20, personality_path="/nonexistent"
        )
        executor = Executor(
            provider=mock_provider, context_assembler=assembler, tool_registry=registry
        )
        plan = Plan(action="scrape", requires_tools=True, tool_params={"url": "https://example.com"})

        _result = await executor.execute("conv-1", "Read this page", plan=plan)

        mock_tool.execute.assert_called_once_with({"url": "https://example.com"})
        mock_provider.complete.assert_called_once()
        call_messages = mock_provider.complete.call_args[0][0]
        system_content = call_messages[0]["content"]
        assert "article content" in system_content
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_core.py::TestExecutor::test_execute_scrape -v`
Expected: FAIL (mock_tool.execute not called -- executor doesn't handle "scrape")

**Step 3: Update the executor**

In `odigos/core/executor.py`, replace the hardcoded `"search"` / `"web_search"` block with a generic tool dispatch:

```python
    async def execute(
        self,
        conversation_id: str,
        message_content: str,
        plan: Plan | None = None,
    ) -> LLMResponse:
        if plan is None:
            plan = Plan(action="respond")

        tool_context = ""

        # Map plan actions to tool names
        _ACTION_TOOLS = {
            "search": "web_search",
            "scrape": "read_page",
        }

        tool_name = _ACTION_TOOLS.get(plan.action)
        if tool_name and self.tool_registry:
            tool = self.tool_registry.get(tool_name)
            if tool:
                try:
                    result = await tool.execute(plan.tool_params)
                    if result.success:
                        tool_context = result.data
                    else:
                        logger.warning("Tool %s failed: %s", tool_name, result.error)
                except Exception:
                    logger.exception("Tool %s raised an exception", tool_name)

        messages = await self.context_assembler.build(
            conversation_id, message_content, tool_context=tool_context
        )
        return await self.provider.complete(messages)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_core.py::TestExecutor -v`
Expected: 5 passed (4 existing + 1 new)

**Step 5: Commit**

```bash
git add odigos/core/executor.py tests/test_core.py
git commit -m "feat: executor handles scrape action via generic tool dispatch"
```

---

### Task 7: Reflector upgrade -- log scrapes to scraped_pages

**Files:**
- Modify: `odigos/core/reflector.py`
- Modify: `tests/test_core.py` (add TestReflectorScrapeLog class)

**Context:** After a scrape, the reflector logs the URL, title, and a summary (first ~200 chars of content) to the `scraped_pages` table. The reflector needs to know whether a scrape happened -- we pass this via an optional `scrape_result` parameter.

Reference `odigos/core/reflector.py` for the current reflect method signature.

**Step 1: Write the failing test**

Add a new test class to `tests/test_core.py`:

```python
class TestReflectorScrapeLog:
    async def test_logs_scrape_to_db(self, db: Database):
        """Reflector logs scrape metadata to scraped_pages table."""
        reflector = Reflector(db=db)
        response = LLMResponse(
            content="Here's a summary of the page.",
            model="test/model",
            tokens_in=10,
            tokens_out=20,
            cost_usd=0.001,
        )

        await db.execute(
            "INSERT INTO conversations (id, channel) VALUES (?, ?)",
            ("conv-scrape", "test"),
        )

        await reflector.reflect(
            "conv-scrape",
            response,
            user_message="Read this page",
            scrape_metadata={"url": "https://example.com/article", "title": "Example Article", "content": "This is the main article content about testing."},
        )

        row = await db.fetch_one(
            "SELECT url, title, summary FROM scraped_pages WHERE url = ?",
            ("https://example.com/article",),
        )
        assert row is not None
        assert row["url"] == "https://example.com/article"
        assert row["title"] == "Example Article"
        assert "main article content" in row["summary"]

    async def test_no_scrape_metadata_no_log(self, db: Database):
        """Without scrape_metadata, no scraped_pages entry is created."""
        reflector = Reflector(db=db)
        response = LLMResponse(
            content="Normal response.",
            model="test/model",
            tokens_in=10,
            tokens_out=5,
            cost_usd=0.001,
        )

        await db.execute(
            "INSERT INTO conversations (id, channel) VALUES (?, ?)",
            ("conv-no-scrape", "test"),
        )

        await reflector.reflect("conv-no-scrape", response, user_message="Hello")

        rows = await db.fetch_all("SELECT * FROM scraped_pages")
        assert len(rows) == 0
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_core.py::TestReflectorScrapeLog -v`
Expected: FAIL (reflect() got unexpected keyword argument 'scrape_metadata')

**Step 3: Update the reflector**

In `odigos/core/reflector.py`, add `scrape_metadata` parameter to `reflect()`:

```python
    async def reflect(
        self,
        conversation_id: str,
        response: LLMResponse,
        user_message: str | None = None,
        scrape_metadata: dict | None = None,
    ) -> None:
```

At the end of the method (after the existing memory manager block), add:

```python
        # Log scrape if metadata provided
        if scrape_metadata:
            url = scrape_metadata.get("url", "")
            title = scrape_metadata.get("title", "")
            content = scrape_metadata.get("content", "")
            summary = content[:200] if content else ""
            await self.db.execute(
                "INSERT INTO scraped_pages (id, url, title, summary) VALUES (?, ?, ?, ?)",
                (str(uuid.uuid4()), url, title, summary),
            )
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_core.py::TestReflectorScrapeLog -v`
Expected: 2 passed

Also run all reflector tests to ensure no regression:

Run: `uv run pytest tests/test_core.py -k "Reflector" -v`
Expected: All reflector tests pass

**Step 5: Commit**

```bash
git add odigos/core/reflector.py tests/test_core.py
git commit -m "feat: reflector logs scrape metadata to scraped_pages table"
```

---

### Task 8: Agent wiring -- pass scrape metadata through the loop

**Files:**
- Modify: `odigos/core/agent.py:44-64`
- Modify: `odigos/core/executor.py` (return scrape_metadata alongside response)
- Modify: `tests/test_core.py` (TestAgent class)

**Context:** The agent's `handle_message` calls planner -> executor -> reflector. For scrape actions, the executor needs to pass the scraped page metadata back so the agent can give it to the reflector. We add a simple return tuple from executor when scrape metadata is available.

Reference `odigos/core/agent.py` for the current flow and `odigos/core/executor.py` for the execute method.

**Step 1: Write the failing test**

Add to `TestAgent` in `tests/test_core.py`:

```python
    async def test_scrape_flow(self, db: Database, mock_provider: AsyncMock):
        """Agent performs scrape when planner classifies as scrape intent."""
        mock_planner_provider = AsyncMock()
        mock_planner_provider.complete.return_value = LLMResponse(
            content='{"action": "scrape", "url": "https://example.com/page"}',
            model="test/model",
            tokens_in=5,
            tokens_out=10,
            cost_usd=0.0,
        )

        mock_tool = AsyncMock()
        mock_tool.name = "read_page"
        mock_tool.execute.return_value = ToolResult(
            success=True, data="## Page: Example\n\n**URL:** https://example.com/page\n\nPage content here."
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
        message = _make_message("Read this: https://example.com/page")

        response = await agent.handle_message(message)
        assert response == "I'm Odigos, your assistant."

        mock_tool.execute.assert_called_once()

        # Verify scrape was logged
        row = await db.fetch_one("SELECT url FROM scraped_pages LIMIT 1")
        assert row is not None
        assert row["url"] == "https://example.com/page"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_core.py::TestAgent::test_scrape_flow -v`
Expected: FAIL (scraped_pages table has no rows -- metadata not passed to reflector)

**Step 3: Update executor to return scrape metadata**

In `odigos/core/executor.py`, add a dataclass for the execute result and capture scrape metadata:

```python
@dataclass
class ExecuteResult:
    response: LLMResponse
    scrape_metadata: dict | None = None
```

Update the `execute` method to return `ExecuteResult`:

```python
    async def execute(
        self,
        conversation_id: str,
        message_content: str,
        plan: Plan | None = None,
    ) -> ExecuteResult:
        if plan is None:
            plan = Plan(action="respond")

        tool_context = ""
        scrape_metadata = None

        _ACTION_TOOLS = {
            "search": "web_search",
            "scrape": "read_page",
        }

        tool_name = _ACTION_TOOLS.get(plan.action)
        if tool_name and self.tool_registry:
            tool = self.tool_registry.get(tool_name)
            if tool:
                try:
                    result = await tool.execute(plan.tool_params)
                    if result.success:
                        tool_context = result.data
                        if plan.action == "scrape":
                            scrape_metadata = {
                                "url": plan.tool_params.get("url", ""),
                                "title": "",
                                "content": tool_context,
                            }
                    else:
                        logger.warning("Tool %s failed: %s", tool_name, result.error)
                except Exception:
                    logger.exception("Tool %s raised an exception", tool_name)

        messages = await self.context_assembler.build(
            conversation_id, message_content, tool_context=tool_context
        )
        response = await self.provider.complete(messages)
        return ExecuteResult(response=response, scrape_metadata=scrape_metadata)
```

**Step 4: Update agent to use ExecuteResult**

In `odigos/core/agent.py`, update `handle_message` to unwrap `ExecuteResult` and pass scrape_metadata to reflector:

```python
    async def handle_message(self, message: UniversalMessage) -> str:
        conversation_id = await self._get_or_create_conversation(message)

        await self.db.execute(
            "INSERT INTO messages (id, conversation_id, role, content) VALUES (?, ?, ?, ?)",
            (message.id, conversation_id, "user", message.content),
        )

        plan = await self.planner.plan(message.content)
        result = await self.executor.execute(conversation_id, message.content, plan=plan)
        await self.reflector.reflect(
            conversation_id,
            result.response,
            user_message=message.content,
            scrape_metadata=result.scrape_metadata,
        )

        await self.db.execute(
            "UPDATE conversations SET last_message_at = datetime('now'), "
            "message_count = message_count + 2 WHERE id = ?",
            (conversation_id,),
        )

        return result.response.content
```

**Step 5: Fix existing executor tests**

The existing `TestExecutor` tests expect `execute()` to return an `LLMResponse`, but now it returns `ExecuteResult`. Update them to unwrap `.response`:

- `test_execute_respond`: change `result = await executor.execute(...)` assertions to use `result.response.content`
- `test_execute_search`: already uses `_result`, check system_content assertion still works
- `test_execute_search_tool_failure`: change `result.content` to `result.response.content`
- `test_backward_compat_no_plan`: change `result.content` to `result.response.content`

**Step 6: Run all tests**

Run: `uv run pytest tests/test_core.py -v`
Expected: All tests pass (existing + new scrape flow test)

**Step 7: Commit**

```bash
git add odigos/core/executor.py odigos/core/agent.py tests/test_core.py
git commit -m "feat: wire scrape metadata through agent loop to reflector"
```

---

### Task 9: Main.py wiring -- register scrape tool

**Files:**
- Modify: `odigos/main.py:75-90`

**Context:** The scraper provider needs no config (no API keys). We always initialize it and register the scrape tool. If SearXNG is also configured, both tools are in the same registry. Reference `odigos/main.py` for the current tool registry initialization pattern.

**Step 1: Update main.py**

In `odigos/main.py`, add `_scraper` to the module-level refs:

```python
_scraper = None
```

In the lifespan function, initialize the scraper and register the tool. The scraper should always be initialized (no config needed). Update the tool registry block:

```python
    # Initialize tool registry and tools
    from odigos.providers.scraper import ScraperProvider
    from odigos.tools.registry import ToolRegistry
    from odigos.tools.scrape import ScrapeTool

    _scraper = ScraperProvider()
    tool_registry = ToolRegistry()

    scrape_tool = ScrapeTool(scraper=_scraper)
    tool_registry.register(scrape_tool)
    logger.info("Scrape tool initialized")

    # Add search tool if SearXNG is configured
    if settings.searxng_url:
        from odigos.providers.searxng import SearxngProvider
        from odigos.tools.search import SearchTool

        _searxng = SearxngProvider(
            url=settings.searxng_url,
            username=settings.searxng_username,
            password=settings.searxng_password,
        )
        search_tool = SearchTool(searxng=_searxng)
        tool_registry.register(search_tool)
        logger.info("Search tool initialized (SearXNG: %s)", settings.searxng_url)
```

In shutdown, add scraper cleanup before searxng:

```python
    if _scraper:
        await _scraper.close()
```

**Step 2: Verify no import errors**

Run: `uv run python -c "from odigos.main import app; print('OK')"`
Expected: `OK`

**Step 3: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests pass

**Step 4: Commit**

```bash
git add odigos/main.py
git commit -m "feat: wire scraper provider and read_page tool in main"
```

---

### Task 10: Final verification

**Files:** None (verification only)

**Step 1: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests pass

**Step 2: Run linter**

Run: `uv run ruff check odigos/ tests/`
Expected: No errors

**Step 3: Run formatter**

Run: `uv run ruff format odigos/ tests/`
Expected: Files formatted (commit any changes)

**Step 4: Review file tree**

Run: `find odigos/providers/scraper.py odigos/tools/scrape.py migrations/003_scraped_pages.sql tests/test_scraper.py tests/test_tools_scrape.py -type f`
Expected: All 5 new files exist

**Step 5: Commit any formatting fixes**

```bash
git add -A
git commit -m "style: format phase 2e files"
```
