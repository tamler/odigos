# Phase 3a: Quick Wins Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add async cost lookup from OpenRouter, replace httpx with StealthyFetcher for robust scraping, and add document processing via docling.

**Architecture:** Three independent components. Cost lookup is fire-and-forget from Reflector. Scraper replaces httpx entirely with Scrapling fetchers (no fallback). Document processing adds a new provider, tool, planner action, and Telegram file handling.

**Tech Stack:** httpx (cost lookup only), scrapling[fetchers] (StealthyFetcher + PlayWrightFetcher), docling (DocumentConverter)

---

## Task 1: Add `fetch_generation_cost` to OpenRouterProvider

**Files:**
- Modify: `odigos/providers/openrouter.py`
- Test: `tests/test_openrouter.py`

**Step 1: Write the failing test**

In `tests/test_openrouter.py`, add:

```python
import httpx
import pytest
from unittest.mock import AsyncMock, patch

from odigos.providers.openrouter import OpenRouterProvider


@pytest.fixture
def provider():
    return OpenRouterProvider(
        api_key="test-key",
        default_model="test/model",
        fallback_model="test/fallback",
    )


class TestFetchGenerationCost:
    async def test_fetch_generation_cost_returns_total_cost(self, provider):
        mock_response = httpx.Response(
            200,
            json={"data": {"total_cost": 0.00042}},
            request=httpx.Request("GET", "https://example.com"),
        )
        with patch.object(provider._client, "get", new_callable=AsyncMock, return_value=mock_response):
            cost = await provider.fetch_generation_cost("gen-123")
        assert cost == 0.00042

    async def test_fetch_generation_cost_returns_none_on_error(self, provider):
        with patch.object(
            provider._client, "get", new_callable=AsyncMock, side_effect=httpx.HTTPError("fail")
        ):
            cost = await provider.fetch_generation_cost("gen-123")
        assert cost is None

    async def test_fetch_generation_cost_returns_none_on_missing_data(self, provider):
        mock_response = httpx.Response(
            200,
            json={"data": {}},
            request=httpx.Request("GET", "https://example.com"),
        )
        with patch.object(provider._client, "get", new_callable=AsyncMock, return_value=mock_response):
            cost = await provider.fetch_generation_cost("gen-123")
        assert cost is None
```

Note: The existing tests in `test_openrouter.py` test `generation_id` extraction. Keep those. If `test_openrouter.py` already has a `provider` fixture, merge them or adjust scope. Existing tests use `from odigos.providers.openrouter import OpenRouterProvider` and `from odigos.providers.base import LLMResponse` -- check if they already have a `provider` fixture; if so, reuse it.

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_openrouter.py::TestFetchGenerationCost -v`
Expected: FAIL with `AttributeError: 'OpenRouterProvider' object has no attribute 'fetch_generation_cost'`

**Step 3: Write minimal implementation**

In `odigos/providers/openrouter.py`, add this method to `OpenRouterProvider` after the `_call` method:

```python
OPENROUTER_GENERATION_URL = "https://openrouter.ai/api/v1/generation"
```

Add at the top of the file (constant, alongside `OPENROUTER_API_URL`).

Then in the class body:

```python
async def fetch_generation_cost(self, generation_id: str) -> float | None:
    """Fetch actual cost from OpenRouter's generation endpoint. Returns None on failure."""
    try:
        response = await self._client.get(
            OPENROUTER_GENERATION_URL,
            params={"id": generation_id},
        )
        if response.status_code != 200:
            return None
        data = response.json().get("data", {})
        cost = data.get("total_cost")
        if cost is not None:
            return float(cost)
        return None
    except Exception:
        logger.debug("Failed to fetch generation cost for %s", generation_id, exc_info=True)
        return None
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_openrouter.py -v`
Expected: ALL PASS (both new and existing tests)

**Step 5: Commit**

```bash
git add odigos/providers/openrouter.py tests/test_openrouter.py
git commit -m "feat: add fetch_generation_cost to OpenRouterProvider"
```

---

## Task 2: Add async cost backfill to Reflector

**Files:**
- Modify: `odigos/core/reflector.py`
- Test: `tests/test_reflector_cost.py` (new)

**Context:** The Reflector stores assistant messages in `reflect()`. After storing, if the response has a `generation_id`, we spawn a fire-and-forget task that waits ~2 seconds, fetches the real cost, and updates the message row. The Reflector needs access to the OpenRouter provider (or a callable that fetches cost).

**Step 1: Write the failing test**

Create `tests/test_reflector_cost.py`:

```python
import asyncio
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from odigos.core.reflector import Reflector
from odigos.db import Database
from odigos.providers.base import LLMResponse


@pytest.fixture
async def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    db = Database(db_path)
    await db.initialize()
    yield db
    await db.close()


class TestAsyncCostBackfill:
    async def test_spawns_cost_task_when_generation_id_present(self, db):
        mock_fetch = AsyncMock(return_value=0.00042)
        reflector = Reflector(db, cost_fetcher=mock_fetch)

        response = LLMResponse(
            content="Hello",
            model="test/model",
            tokens_in=10,
            tokens_out=20,
            cost_usd=0.0,
            generation_id="gen-abc-123",
        )

        await reflector.reflect("conv-1", response)

        # Wait for the background task to complete
        await asyncio.sleep(0.1)

        mock_fetch.assert_called_once_with("gen-abc-123")

        # Verify the cost was updated in the database
        row = await db.fetch_one(
            "SELECT cost_usd FROM messages WHERE conversation_id = ? AND role = 'assistant'",
            ("conv-1",),
        )
        assert row["cost_usd"] == pytest.approx(0.00042)

    async def test_no_task_spawned_when_no_generation_id(self, db):
        mock_fetch = AsyncMock()
        reflector = Reflector(db, cost_fetcher=mock_fetch)

        response = LLMResponse(
            content="Hello",
            model="test/model",
            tokens_in=10,
            tokens_out=20,
            cost_usd=0.0,
            generation_id=None,
        )

        await reflector.reflect("conv-1", response)
        await asyncio.sleep(0.1)

        mock_fetch.assert_not_called()

    async def test_cost_fetch_failure_leaves_original_cost(self, db):
        mock_fetch = AsyncMock(return_value=None)
        reflector = Reflector(db, cost_fetcher=mock_fetch)

        response = LLMResponse(
            content="Hello",
            model="test/model",
            tokens_in=10,
            tokens_out=20,
            cost_usd=0.001,
            generation_id="gen-xyz",
        )

        await reflector.reflect("conv-1", response)
        await asyncio.sleep(0.1)

        row = await db.fetch_one(
            "SELECT cost_usd FROM messages WHERE conversation_id = ? AND role = 'assistant'",
            ("conv-1",),
        )
        assert row["cost_usd"] == pytest.approx(0.001)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_reflector_cost.py -v`
Expected: FAIL (Reflector doesn't accept `cost_fetcher` param yet)

**Step 3: Write minimal implementation**

Modify `odigos/core/reflector.py`:

1. Add `import asyncio` at the top.

2. Update `__init__` to accept an optional `cost_fetcher`:

```python
def __init__(
    self,
    db: Database,
    memory_manager: MemoryManager | None = None,
    cost_fetcher: typing.Callable | None = None,
) -> None:
    self.db = db
    self.memory_manager = memory_manager
    self._cost_fetcher = cost_fetcher
```

Add `import typing` to the imports (or use `from collections.abc import Callable`).

3. In `reflect()`, after the message INSERT (after line 67), add:

```python
# Spawn async cost backfill if generation_id is available
if response.generation_id and self._cost_fetcher:
    # We need the message ID we just inserted to update it later
    asyncio.create_task(
        self._backfill_cost(msg_id, response.generation_id)
    )
```

Where `msg_id` is the `str(uuid.uuid4())` used in the INSERT -- extract it to a variable before the INSERT:

```python
msg_id = str(uuid.uuid4())
await self.db.execute(
    "INSERT INTO messages ...",
    (msg_id, conversation_id, "assistant", content, ...),
)

if response.generation_id and self._cost_fetcher:
    asyncio.create_task(self._backfill_cost(msg_id, response.generation_id))
```

4. Add the `_backfill_cost` method:

```python
async def _backfill_cost(self, message_id: str, generation_id: str) -> None:
    """Background task: fetch real cost from OpenRouter and update the message."""
    try:
        cost = await self._cost_fetcher(generation_id)
        if cost is not None:
            await self.db.execute(
                "UPDATE messages SET cost_usd = ? WHERE id = ?",
                (cost, message_id),
            )
            logger.debug("Updated cost for message %s: $%.6f", message_id, cost)
    except Exception:
        logger.debug("Cost backfill failed for %s", generation_id, exc_info=True)
```

Note: The design says wait ~2 seconds, but for testability we skip the delay in the core method. The delay will be applied when we wire it in `main.py` (Task 3) by wrapping the fetcher with a delay. For now, keep it simple.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_reflector_cost.py -v`
Expected: ALL PASS

Also run: `uv run pytest tests/ -v` to make sure nothing else broke (existing tests pass `cost_fetcher=None` by default).

**Step 5: Commit**

```bash
git add odigos/core/reflector.py tests/test_reflector_cost.py
git commit -m "feat: async cost backfill in Reflector"
```

---

## Task 3: Wire cost lookup in main.py

**Files:**
- Modify: `odigos/main.py`
- Modify: `odigos/core/agent.py`

No new tests -- this is wiring. The integration is covered by Tasks 1 and 2 tests.

**Step 1: Update Agent to pass cost_fetcher to Reflector**

In `odigos/core/agent.py`, add `cost_fetcher` parameter:

```python
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
    skill_registry: SkillRegistry | None = None,
    cost_fetcher: typing.Callable | None = None,
) -> None:
    ...
    self.reflector = Reflector(db, memory_manager=memory_manager, cost_fetcher=cost_fetcher)
```

Add `import typing` or `from collections.abc import Callable` to the imports.

**Step 2: Wire in main.py**

In `odigos/main.py`, after the OpenRouterProvider is created, create a delayed cost fetcher:

```python
import asyncio

# Create a delayed cost fetcher for async backfill
async def _delayed_cost_fetcher(generation_id: str) -> float | None:
    await asyncio.sleep(2)
    return await _provider.fetch_generation_cost(generation_id)
```

Then pass it to the Agent:

```python
agent = Agent(
    db=_db,
    provider=_router,
    agent_name=settings.agent.name,
    memory_manager=memory_manager,
    personality_path=settings.personality.path,
    planner_provider=_router,
    tool_registry=tool_registry,
    skill_registry=skill_registry,
    cost_fetcher=_delayed_cost_fetcher,
)
```

**Step 3: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add odigos/core/agent.py odigos/main.py
git commit -m "feat: wire async cost lookup from OpenRouter"
```

---

## Task 4: Update pyproject.toml for scrapling[fetchers] and docling

**Files:**
- Modify: `pyproject.toml`

**Step 1: Update dependencies**

Change `"scrapling>=0.3.0"` to `"scrapling[fetchers]>=0.3.0"` and add `"docling>=2.0.0"`:

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
    "scrapling[fetchers]>=0.3.0",
    "docling>=2.0.0",
]
```

**Step 2: Install updated dependencies**

Run: `uv sync`

**Step 3: Run tests to make sure nothing broke**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "deps: add scrapling[fetchers] and docling"
```

---

## Task 5: Replace httpx with StealthyFetcher in ScraperProvider

**Files:**
- Modify: `odigos/providers/scraper.py`
- Test: `tests/test_scraper.py` (new)

**Context:** Currently `ScraperProvider` uses `httpx.AsyncClient` to fetch pages and `scrapling.parser.Adaptor` to parse HTML. We replace httpx with `StealthyFetcher` for the default tier and `PlayWrightFetcher` for the browser tier. StealthyFetcher and PlayWrightFetcher are synchronous -- they return an `Adaptor` object directly. We run them in a thread executor since they're blocking.

Check Scrapling's API: `StealthyFetcher.fetch(url)` returns an `Adaptor` (already parsed). `PlayWrightFetcher.fetch(url)` also returns an `Adaptor`. Both are synchronous calls.

**Step 1: Write the failing test**

Create `tests/test_scraper.py`:

```python
import asyncio
from unittest.mock import MagicMock, patch

import pytest

from odigos.providers.scraper import ScraperProvider, ScrapedPage


class TestScraperProvider:
    async def test_scrape_standard_tier(self):
        scraper = ScraperProvider()

        mock_adaptor = MagicMock()
        mock_adaptor.css.return_value.get.return_value = "Test Page Title"

        mock_content_element = MagicMock()
        mock_content_element.get_all_text.return_value = "Article content here"
        mock_adaptor.css.side_effect = [
            # First call: title selector
            MagicMock(get=MagicMock(return_value="Test Page Title")),
            # Second call onward: content selectors
            [mock_content_element],
        ]

        with patch("odigos.providers.scraper.StealthyFetcher") as MockFetcher:
            MockFetcher.fetch.return_value = mock_adaptor
            result = await scraper.scrape("https://example.com")

        assert isinstance(result, ScrapedPage)
        assert result.url == "https://example.com"
        MockFetcher.fetch.assert_called_once()

    async def test_scrape_browser_tier(self):
        scraper = ScraperProvider()

        mock_adaptor = MagicMock()
        mock_adaptor.css.return_value.get.return_value = "JS Page"
        mock_content = MagicMock()
        mock_content.get_all_text.return_value = "Dynamic content"
        mock_adaptor.css.side_effect = [
            MagicMock(get=MagicMock(return_value="JS Page")),
            [mock_content],
        ]

        with patch("odigos.providers.scraper.PlayWrightFetcher") as MockFetcher:
            MockFetcher.fetch.return_value = mock_adaptor
            result = await scraper.scrape("https://example.com", tier="browser")

        assert isinstance(result, ScrapedPage)
        MockFetcher.fetch.assert_called_once()

    async def test_scrape_returns_empty_on_failure(self):
        scraper = ScraperProvider()

        with patch("odigos.providers.scraper.StealthyFetcher") as MockFetcher:
            MockFetcher.fetch.side_effect = Exception("Connection failed")
            result = await scraper.scrape("https://bad-url.example.com")

        assert result.content == ""
        assert result.title == ""

    async def test_scrape_truncates_long_content(self):
        scraper = ScraperProvider(max_content_chars=50)

        mock_adaptor = MagicMock()
        mock_adaptor.css.return_value.get.return_value = "Title"
        mock_content = MagicMock()
        mock_content.get_all_text.return_value = "x" * 100
        mock_adaptor.css.side_effect = [
            MagicMock(get=MagicMock(return_value="Title")),
            [mock_content],
        ]

        with patch("odigos.providers.scraper.StealthyFetcher") as MockFetcher:
            MockFetcher.fetch.return_value = mock_adaptor
            result = await scraper.scrape("https://example.com")

        assert len(result.content) < 100
        assert result.content.endswith("[truncated]")

    async def test_close_is_noop(self):
        """ScraperProvider no longer has an httpx client to close."""
        scraper = ScraperProvider()
        await scraper.close()  # Should not raise
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scraper.py -v`
Expected: FAIL (ScraperProvider still uses httpx, doesn't have `tier` param, etc.)

**Step 3: Rewrite ScraperProvider**

Replace `odigos/providers/scraper.py` entirely:

```python
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from scrapling.fetchers import StealthyFetcher, PlayWrightFetcher

logger = logging.getLogger(__name__)

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
    """Fetches web pages using Scrapling fetchers and extracts clean text content.

    Tiers:
        - "standard": StealthyFetcher (anti-bot evasion, default)
        - "browser": PlayWrightFetcher (full browser rendering for JS-heavy sites)
    """

    def __init__(self, max_content_chars: int = 4000) -> None:
        self.max_content_chars = max_content_chars

    async def scrape(self, url: str, tier: str = "standard") -> ScrapedPage:
        """Fetch and parse a web page. Returns ScrapedPage with extracted content."""
        try:
            page = await asyncio.to_thread(self._fetch, url, tier)
        except Exception:
            logger.warning("Failed to fetch %s (tier=%s)", url, tier, exc_info=True)
            return ScrapedPage(url=url, title="", content="")

        try:
            title = page.css("title::text").get() or ""

            content_text = ""
            for selector in _CONTENT_SELECTORS:
                elements = page.css(selector)
                if elements:
                    content_text = elements[0].get_all_text(separator="\n", strip=True)
                    break

            if not content_text:
                body = page.css("body")
                if body:
                    content_text = body[0].get_all_text(separator="\n", strip=True)

            if len(content_text) > self.max_content_chars:
                content_text = content_text[: self.max_content_chars] + "\n\n[truncated]"

            return ScrapedPage(url=url, title=title, content=content_text)

        except Exception:
            logger.warning("Failed to parse content from %s", url, exc_info=True)
            return ScrapedPage(url=url, title="", content="")

    @staticmethod
    def _fetch(url: str, tier: str):
        """Synchronous fetch -- runs in thread executor."""
        if tier == "browser":
            return PlayWrightFetcher.fetch(url)
        return StealthyFetcher.fetch(url)

    async def close(self) -> None:
        """No persistent client to close."""
        pass
```

Key changes:
- Removed `httpx` import entirely
- Imported `StealthyFetcher` and `PlayWrightFetcher` from `scrapling.fetchers`
- `scrape()` now accepts `tier` parameter (default "standard")
- Fetching runs in `asyncio.to_thread()` since scrapling fetchers are synchronous
- `close()` is now a no-op (no httpx client)
- Parsing logic (CSS selectors, content extraction, truncation) is unchanged

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_scraper.py -v`
Expected: ALL PASS

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

**Step 5: Lint check**

Run: `uv run ruff check odigos/providers/scraper.py`
Expected: Clean

**Step 6: Commit**

```bash
git add odigos/providers/scraper.py tests/test_scraper.py
git commit -m "feat: replace httpx with StealthyFetcher/PlayWrightFetcher"
```

---

## Task 6: Pass tier parameter through ScrapeTool

**Files:**
- Modify: `odigos/tools/scrape.py`
- Test: `tests/test_scrape_tool.py` (new, or add to existing)

**Step 1: Write the failing test**

Create `tests/test_scrape_tool.py`:

```python
from unittest.mock import AsyncMock

import pytest

from odigos.providers.scraper import ScrapedPage
from odigos.tools.scrape import ScrapeTool


class TestScrapeTool:
    async def test_passes_tier_to_scraper(self):
        mock_scraper = AsyncMock()
        mock_scraper.scrape.return_value = ScrapedPage(
            url="https://example.com", title="Test", content="Content"
        )

        tool = ScrapeTool(scraper=mock_scraper)
        result = await tool.execute({"url": "https://example.com", "tier": "browser"})

        mock_scraper.scrape.assert_called_once_with("https://example.com", tier="browser")
        assert result.success is True

    async def test_defaults_to_standard_tier(self):
        mock_scraper = AsyncMock()
        mock_scraper.scrape.return_value = ScrapedPage(
            url="https://example.com", title="Test", content="Content"
        )

        tool = ScrapeTool(scraper=mock_scraper)
        result = await tool.execute({"url": "https://example.com"})

        mock_scraper.scrape.assert_called_once_with("https://example.com", tier="standard")
        assert result.success is True
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scrape_tool.py -v`
Expected: FAIL (ScrapeTool doesn't pass `tier`)

**Step 3: Update ScrapeTool**

Read `odigos/tools/scrape.py` first to see the current implementation, then modify to pass `tier`:

The key change is in `execute()` -- extract `tier` from params and pass it:

```python
async def execute(self, params: dict) -> ToolResult:
    url = params.get("url", "")
    tier = params.get("tier", "standard")
    if not url:
        return ToolResult(success=False, data="", error="No URL provided")

    result = await self.scraper.scrape(url, tier=tier)
    ...
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_scrape_tool.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add odigos/tools/scrape.py tests/test_scrape_tool.py
git commit -m "feat: pass tier parameter through ScrapeTool"
```

---

## Task 7: Create DoclingProvider

**Files:**
- Create: `odigos/providers/docling.py`
- Test: `tests/test_docling.py` (new)

**Step 1: Write the failing test**

Create `tests/test_docling.py`:

```python
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from odigos.providers.docling import ConvertedDocument, DoclingProvider


class TestDoclingProvider:
    def test_convert_returns_markdown_content(self):
        provider = DoclingProvider(max_content_chars=8000)

        mock_doc = MagicMock()
        mock_doc.document.export_to_markdown.return_value = "# Title\n\nSome content here."

        mock_converter = MagicMock()
        mock_converter.convert.return_value = mock_doc

        with patch.object(provider, "_converter", mock_converter):
            result = provider.convert("/tmp/test.pdf")

        assert result.content == "# Title\n\nSome content here."
        assert result.source == "/tmp/test.pdf"
        mock_converter.convert.assert_called_once_with("/tmp/test.pdf")

    def test_convert_truncates_long_content(self):
        provider = DoclingProvider(max_content_chars=50)

        mock_doc = MagicMock()
        mock_doc.document.export_to_markdown.return_value = "x" * 100

        mock_converter = MagicMock()
        mock_converter.convert.return_value = mock_doc

        with patch.object(provider, "_converter", mock_converter):
            result = provider.convert("/tmp/big.pdf")

        assert len(result.content) <= 50 + len("\n\n[truncated]")
        assert result.content.endswith("[truncated]")

    def test_convert_handles_url(self):
        provider = DoclingProvider()

        mock_doc = MagicMock()
        mock_doc.document.export_to_markdown.return_value = "Web content"

        mock_converter = MagicMock()
        mock_converter.convert.return_value = mock_doc

        with patch.object(provider, "_converter", mock_converter):
            result = provider.convert("https://example.com/doc.pdf")

        assert result.source == "https://example.com/doc.pdf"
        mock_converter.convert.assert_called_once_with("https://example.com/doc.pdf")
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_docling.py -v`
Expected: FAIL with `ModuleNotFoundError` or `ImportError`

**Step 3: Write DoclingProvider**

Create `odigos/providers/docling.py`:

```python
from __future__ import annotations

import logging
from dataclasses import dataclass

from docling.document_converter import DocumentConverter

logger = logging.getLogger(__name__)


@dataclass
class ConvertedDocument:
    source: str
    content: str


class DoclingProvider:
    """Converts documents (PDF, DOCX, PPTX, images) to markdown using docling.

    Note: docling's convert() is synchronous. Callers should run in a thread
    executor (asyncio.to_thread) to avoid blocking the event loop.
    """

    def __init__(self, max_content_chars: int = 8000) -> None:
        self.max_content_chars = max_content_chars
        self._converter = DocumentConverter()

    def convert(self, source: str) -> ConvertedDocument:
        """Convert a file path or URL to markdown."""
        result = self._converter.convert(source)
        content = result.document.export_to_markdown()

        if len(content) > self.max_content_chars:
            content = content[: self.max_content_chars] + "\n\n[truncated]"

        return ConvertedDocument(source=source, content=content)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_docling.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add odigos/providers/docling.py tests/test_docling.py
git commit -m "feat: add DoclingProvider for document conversion"
```

---

## Task 8: Create DocTool

**Files:**
- Create: `odigos/tools/document.py`
- Test: `tests/test_doc_tool.py` (new)

**Step 1: Write the failing test**

Create `tests/test_doc_tool.py`:

```python
import asyncio
from unittest.mock import MagicMock, patch

import pytest

from odigos.providers.docling import ConvertedDocument, DoclingProvider
from odigos.tools.document import DocTool


class TestDocTool:
    async def test_execute_with_path(self):
        mock_provider = MagicMock(spec=DoclingProvider)
        mock_provider.convert.return_value = ConvertedDocument(
            source="/tmp/test.pdf", content="# Document\n\nContent here."
        )

        tool = DocTool(provider=mock_provider)
        result = await tool.execute({"path": "/tmp/test.pdf"})

        assert result.success is True
        assert "Content here" in result.data
        mock_provider.convert.assert_called_once_with("/tmp/test.pdf")

    async def test_execute_with_url(self):
        mock_provider = MagicMock(spec=DoclingProvider)
        mock_provider.convert.return_value = ConvertedDocument(
            source="https://example.com/doc.pdf", content="Web doc content"
        )

        tool = DocTool(provider=mock_provider)
        result = await tool.execute({"url": "https://example.com/doc.pdf"})

        assert result.success is True
        assert "Web doc content" in result.data

    async def test_execute_with_no_source(self):
        mock_provider = MagicMock(spec=DoclingProvider)
        tool = DocTool(provider=mock_provider)
        result = await tool.execute({})

        assert result.success is False
        assert "path" in result.error.lower() or "url" in result.error.lower()

    async def test_execute_handles_conversion_error(self):
        mock_provider = MagicMock(spec=DoclingProvider)
        mock_provider.convert.side_effect = Exception("Unsupported format")

        tool = DocTool(provider=mock_provider)
        result = await tool.execute({"path": "/tmp/bad.xyz"})

        assert result.success is False
        assert result.error is not None

    async def test_tool_name_and_description(self):
        mock_provider = MagicMock(spec=DoclingProvider)
        tool = DocTool(provider=mock_provider)
        assert tool.name == "read_document"
        assert "document" in tool.description.lower() or "PDF" in tool.description
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_doc_tool.py -v`
Expected: FAIL with `ModuleNotFoundError` for `odigos.tools.document`

**Step 3: Write DocTool**

Create `odigos/tools/document.py`:

```python
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from odigos.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from odigos.providers.docling import DoclingProvider

logger = logging.getLogger(__name__)


class DocTool(BaseTool):
    """Convert a document (PDF, DOCX, PPTX, image) to readable text."""

    name = "read_document"
    description = "Convert a document (PDF, DOCX, PPTX, image) to readable text."

    def __init__(self, provider: DoclingProvider) -> None:
        self.provider = provider

    async def execute(self, params: dict) -> ToolResult:
        source = params.get("path") or params.get("url")
        if not source:
            return ToolResult(success=False, data="", error="No path or url provided")

        try:
            result = await asyncio.to_thread(self.provider.convert, source)
            return ToolResult(success=True, data=result.content)
        except Exception as e:
            logger.warning("Document conversion failed for %s: %s", source, e, exc_info=True)
            return ToolResult(success=False, data="", error=str(e))
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_doc_tool.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add odigos/tools/document.py tests/test_doc_tool.py
git commit -m "feat: add DocTool for document processing"
```

---

## Task 9: Add document action to Planner and Executor

**Files:**
- Modify: `odigos/core/planner.py`
- Modify: `odigos/core/executor.py`
- Test: `tests/test_core.py` (add tests)

**Step 1: Write the failing tests**

Add to `tests/test_core.py`:

```python
class TestPlannerDocumentAction:
    async def test_classifies_document_request(self):
        mock_provider = AsyncMock()
        mock_provider.complete.return_value = LLMResponse(
            content='{"action": "document", "path": "/tmp/test.pdf", "skill": null}',
            model="test",
            tokens_in=10,
            tokens_out=10,
            cost_usd=0.0,
        )

        planner = Planner(provider=mock_provider)
        plan = await planner.plan("Please read this document")

        assert plan.action == "document"
        assert plan.tool_params.get("path") == "/tmp/test.pdf"

    async def test_classifies_file_attachment(self):
        mock_provider = AsyncMock()
        mock_provider.complete.return_value = LLMResponse(
            content='{"action": "document", "path": "/tmp/odigos/photo.jpg", "skill": null}',
            model="test",
            tokens_in=10,
            tokens_out=10,
            cost_usd=0.0,
        )

        planner = Planner(provider=mock_provider)
        plan = await planner.plan("What does this image say?")

        assert plan.action == "document"
        assert plan.requires_tools is True


class TestExecutorDocumentAction:
    async def test_executor_calls_document_tool(self):
        mock_provider = AsyncMock()
        mock_provider.complete.return_value = LLMResponse(
            content="The document contains meeting notes.",
            model="test",
            tokens_in=50,
            tokens_out=30,
            cost_usd=0.0,
        )

        mock_doc_tool = AsyncMock()
        mock_doc_tool.name = "read_document"
        mock_doc_tool.execute.return_value = ToolResult(
            success=True, data="# Meeting Notes\n\n- Action items listed"
        )

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_doc_tool

        mock_context = AsyncMock()
        mock_context.build.return_value = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Read this document"},
        ]

        executor = Executor(mock_provider, mock_context, tool_registry=mock_registry)
        plan = Plan(
            action="document",
            requires_tools=True,
            tool_params={"path": "/tmp/test.pdf"},
        )

        result = await executor.execute("conv-1", "Read this document", plan=plan)

        mock_registry.get.assert_called_with("read_document")
        mock_doc_tool.execute.assert_called_once_with({"path": "/tmp/test.pdf"})
        assert result.response.content == "The document contains meeting notes."
```

Make sure the necessary imports are at the top of `tests/test_core.py`:
- `from odigos.core.planner import Planner, Plan`
- `from odigos.core.executor import Executor`
- `from odigos.tools.base import ToolResult`

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_core.py::TestPlannerDocumentAction -v`
Expected: FAIL (planner doesn't handle "document" action)

**Step 3: Update Planner**

In `odigos/core/planner.py`, update `CLASSIFY_PROMPT` to add the document action. Add this line to the JSON options:

```
- If processing a document/file is needed: {"action": "document", "path": "<path or URL>", "skill": "<skill or null>"}
```

Add this guidance after the existing guidance lines:

```
Document IS needed for: when the user shares a file attachment, asks about a PDF/document, "read this document", "summarize this PDF", any message with a file attachment or a path to a document.
```

In the `plan()` method, add handling for the "document" action after the "scrape" block:

```python
if action == "document":
    path = result.get("path", "")
    if path:
        return Plan(
            action="document",
            requires_tools=True,
            tool_params={"path": path},
            skill=skill,
        )
```

**Step 4: Update Executor**

In `odigos/core/executor.py`, add "document" to `_ACTION_TOOLS`:

```python
_ACTION_TOOLS = {
    "search": "web_search",
    "scrape": "read_page",
    "document": "read_document",
}
```

**Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_core.py::TestPlannerDocumentAction tests/test_core.py::TestExecutorDocumentAction -v`
Expected: ALL PASS

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add odigos/core/planner.py odigos/core/executor.py tests/test_core.py
git commit -m "feat: add document action to planner and executor"
```

---

## Task 10: Add Telegram file attachment handling

**Files:**
- Modify: `odigos/channels/telegram.py`
- Test: `tests/test_telegram.py` (new)

**Context:** When a user sends a document (PDF, image, etc.) in Telegram, `update.effective_message.document` is set. We need to:
1. Register a handler for document messages
2. Download the file to a temp directory
3. Include the local file path in the UniversalMessage metadata under `"file_path"`
4. Include the file's text caption (if any) as the message content, or a default like "Process this document"

**Step 1: Write the failing test**

Create `tests/test_telegram.py`:

```python
import os
import tempfile
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from odigos.channels.telegram import TelegramChannel


@pytest.fixture
def mock_agent():
    agent = AsyncMock()
    agent.handle_message.return_value = "Document processed."
    return agent


@pytest.fixture
def channel(mock_agent):
    return TelegramChannel(
        token="test-token",
        agent=mock_agent,
        mode="polling",
    )


class TestTelegramDocumentHandler:
    async def test_handle_document_downloads_and_passes_path(self, channel, mock_agent, tmp_path):
        # Create a mock update with a document
        mock_file = AsyncMock()
        mock_file.download_to_drive = AsyncMock()

        update = MagicMock()
        update.effective_message.document.file_name = "report.pdf"
        update.effective_message.document.mime_type = "application/pdf"
        update.effective_message.caption = "Summarize this report"
        update.effective_message.message_id = 42
        update.effective_chat.id = 12345
        update.effective_user.id = 67890
        update.effective_user.username = "testuser"

        context = MagicMock()
        context.bot.get_file = AsyncMock(return_value=mock_file)
        context.bot.send_chat_action = AsyncMock()

        with patch("odigos.channels.telegram.DOCUMENT_DIR", str(tmp_path)):
            await channel._handle_document(update, context)

        # Verify agent was called with file_path in metadata
        call_args = mock_agent.handle_message.call_args[0][0]
        assert call_args.content == "Summarize this report"
        assert "file_path" in call_args.metadata
        assert call_args.metadata["file_path"].endswith("report.pdf")

    async def test_handle_document_uses_default_caption(self, channel, mock_agent, tmp_path):
        mock_file = AsyncMock()
        mock_file.download_to_drive = AsyncMock()

        update = MagicMock()
        update.effective_message.document.file_name = "photo.jpg"
        update.effective_message.document.mime_type = "image/jpeg"
        update.effective_message.caption = None
        update.effective_message.message_id = 43
        update.effective_chat.id = 12345
        update.effective_user.id = 67890
        update.effective_user.username = "testuser"

        context = MagicMock()
        context.bot.get_file = AsyncMock(return_value=mock_file)
        context.bot.send_chat_action = AsyncMock()

        with patch("odigos.channels.telegram.DOCUMENT_DIR", str(tmp_path)):
            await channel._handle_document(update, context)

        call_args = mock_agent.handle_message.call_args[0][0]
        assert "document" in call_args.content.lower() or "file" in call_args.content.lower()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_telegram.py -v`
Expected: FAIL (no `_handle_document` method, no `DOCUMENT_DIR`)

**Step 3: Update TelegramChannel**

In `odigos/channels/telegram.py`:

1. Add imports at top:

```python
import os
import tempfile
```

2. Add constant:

```python
DOCUMENT_DIR = os.path.join(tempfile.gettempdir(), "odigos")
```

3. In `start()`, register an additional handler for documents:

```python
self._app.add_handler(MessageHandler(filters.Document.ALL, self._handle_document))
```

4. Add the `_handle_document` method:

```python
async def _handle_document(self, update: Update, context) -> None:
    """Handle incoming document/file messages."""
    if not update.effective_message or not update.effective_message.document:
        return

    try:
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id, action=ChatAction.TYPING
        )
    except Exception:
        pass

    # Download file to temp directory
    doc = update.effective_message.document
    os.makedirs(DOCUMENT_DIR, exist_ok=True)
    file_path = os.path.join(DOCUMENT_DIR, doc.file_name or f"file_{update.effective_message.message_id}")

    try:
        tg_file = await context.bot.get_file(doc.file_id)
        await tg_file.download_to_drive(file_path)
    except Exception:
        logger.exception("Failed to download document")
        await update.effective_message.reply_text("Failed to download the file. Please try again.")
        return

    # Use caption as message content, or a default
    content = update.effective_message.caption or "Process this document"

    message = UniversalMessage(
        id=str(update.effective_message.message_id),
        channel="telegram",
        sender=str(update.effective_user.id),
        content=content,
        timestamp=datetime.now(timezone.utc),
        metadata={
            "chat_id": update.effective_chat.id,
            "username": getattr(update.effective_user, "username", None),
            "file_path": file_path,
        },
    )

    try:
        response = await self.agent.handle_message(message)
        await update.effective_message.reply_text(response)
    except Exception:
        logger.exception("Error handling document message")
        await update.effective_message.reply_text("Something went wrong. Please try again.")
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_telegram.py -v`
Expected: ALL PASS

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add odigos/channels/telegram.py tests/test_telegram.py
git commit -m "feat: handle Telegram document attachments"
```

---

## Task 11: Wire DoclingProvider and DocTool in main.py

**Files:**
- Modify: `odigos/main.py`

No new tests -- this is wiring. The DoclingProvider and DocTool are tested independently.

**Step 1: Add DoclingProvider and DocTool initialization**

In `odigos/main.py`, after the scrape tool registration block:

```python
# Initialize document processing
from odigos.providers.docling import DoclingProvider
from odigos.tools.document import DocTool

docling_provider = DoclingProvider()
doc_tool = DocTool(provider=docling_provider)
tool_registry.register(doc_tool)
logger.info("Document tool initialized (docling)")
```

**Step 2: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

**Step 3: Lint check**

Run: `uv run ruff check odigos/ tests/`
Expected: Clean

**Step 4: Commit**

```bash
git add odigos/main.py
git commit -m "feat: wire DoclingProvider and DocTool in main"
```

---

## Task 12: Final verification

**Files:** None new.

**Step 1: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

**Step 2: Lint check**

Run: `uv run ruff check odigos/ tests/`
Expected: Clean (fix any issues)

**Step 3: Verify imports work**

Run: `uv run python -c "from odigos.providers.docling import DoclingProvider; print('docling OK')"`
Run: `uv run python -c "from scrapling.fetchers import StealthyFetcher, PlayWrightFetcher; print('scrapling OK')"`

**Step 4: Commit if any fixes were needed**

```bash
git add -A
git commit -m "chore: phase 3a final lint/fixes"
```
