# Phase 3a Design: Quick Wins -- Cost Lookup, StealthyFetcher, Document Processing

**Date:** 2026-03-05
**Status:** Approved
**Milestone:** "It's capable" -- the agent tracks real costs, scrapes anti-bot sites, and reads documents.

---

## Scope

Three independent components, each a self-contained upgrade:

1. **Async cost lookup** -- backfill real costs from OpenRouter after each LLM call
2. **StealthyFetcher upgrade** -- replace httpx with Scrapling's StealthyFetcher for robust scraping
3. **Document processing** -- new `read_document` tool using docling for PDF/DOCX/PPTX/image conversion

Deferred: research skill augmentation, scheduling/reminders (Phase 3b), web UI (Phase 3c).

### Decisions

| Decision | Choice | Reasoning |
|----------|--------|-----------|
| Cost lookup trigger | Fire-and-forget from Reflector | Message is already stored with estimated cost; async task backfills real cost. |
| Fetcher default | StealthyFetcher always | No fallbacks, no conditional imports. We install scrapling[fetchers] and use it. |
| Fetcher tiers | standard (StealthyFetcher) + browser (PlayWrightFetcher) | Two tiers only. Standard is the default. Browser for JS-heavy sites. |
| Document library | docling | Best quality extraction, handles PDF/DOCX/PPTX/images/OCR. Heavy but worth it. |
| Document delivery | Telegram file download -> temp path -> docling | Telegram channel handles attachments, passes local path to tool. |

---

## Component 1: Async Cost Lookup

### OpenRouter Generation Endpoint

After each LLM call, the response includes a `generation_id`. OpenRouter exposes actual cost data at:

```
GET https://openrouter.ai/api/v1/generation?id={generation_id}
```

Response includes `total_cost` (float, USD).

### Flow

1. `Reflector.reflect()` stores the assistant message (with estimated `cost_usd`)
2. After storing, if `response.generation_id` is set, spawn `asyncio.create_task()` to:
   a. Wait ~2 seconds (generation data may not be immediately available)
   b. `GET /api/v1/generation?id={generation_id}`
   c. Extract `total_cost` from response
   d. `UPDATE messages SET cost_usd = ? WHERE id = ?`

### Changes

- **`odigos/core/reflector.py`**: After storing message, spawn async cost update task. Needs the httpx client from the provider or its own lightweight client.
- **`odigos/providers/openrouter.py`**: Add `async def fetch_generation_cost(generation_id: str) -> float | None` method that calls the generation endpoint.
- **No new config.** Uses the existing OpenRouter API key.

### Error Handling

Log and discard on failure. The estimated cost from token counts is already stored as the baseline. This is best-effort enrichment.

---

## Component 2: StealthyFetcher Upgrade

### Current State

`ScraperProvider` uses `httpx.AsyncClient` with a static User-Agent. Works for simple sites but gets blocked by anti-bot protections.

### New State

Replace httpx entirely with Scrapling's built-in fetchers:

- **`StealthyFetcher`**: Default. Anti-bot evasion, rotating headers, TLS fingerprinting.
- **`PlayWrightFetcher`**: For JS-heavy sites. Full browser rendering.

### Interface Change

```python
async def scrape(self, url: str, tier: str = "standard") -> ScrapedPage:
    # tier="standard" -> StealthyFetcher
    # tier="browser"  -> PlayWrightFetcher
```

### Changes

- **`odigos/providers/scraper.py`**: Remove httpx client. Import `StealthyFetcher` and `PlayWrightFetcher` from scrapling. Create fetcher per request (they're lightweight). Parse response with existing CSS selector logic.
- **`odigos/tools/scrape.py`**: Pass `tier` from params if provided, default "standard".
- **`pyproject.toml`**: Change `scrapling>=0.3.0` to `scrapling[fetchers]>=0.3.0`.
- **Setup**: Run `scrapling install` once for browser/fetcher dependencies.

### No Fallbacks

We install `scrapling[fetchers]` and `scrapling install`. If it's not installed, it fails loudly. No conditional imports.

---

## Component 3: Document Processing (Docling)

### New Tool: `read_document`

Converts documents (PDF, DOCX, PPTX, images, etc.) to markdown using docling.

### Provider: `DoclingProvider` (`providers/docling.py`)

```python
class DoclingProvider:
    def __init__(self, max_content_chars: int = 8000) -> None:
        self.max_content_chars = max_content_chars
        self._converter = DocumentConverter()

    def convert(self, source: str) -> ConvertedDocument:
        """Convert a file path or URL to markdown."""
        result = self._converter.convert(source)
        content = result.document.export_to_markdown()
        # truncate if needed
        ...
```

Note: docling's `convert()` is synchronous. We'll run it in a thread executor to avoid blocking the event loop.

### Tool: `DocTool` (`tools/document.py`)

```python
class DocTool(BaseTool):
    name = "read_document"
    description = "Convert a document (PDF, DOCX, PPTX, image) to readable text."

    async def execute(self, params: dict) -> ToolResult:
        source = params.get("path") or params.get("url")
        # Run synchronous docling in thread pool
        result = await asyncio.to_thread(self.provider.convert, source)
        return ToolResult(success=True, data=result.content)
```

### Planner Update

Add document action to `CLASSIFY_PROMPT`:

```
- If processing a document/file is needed: {"action": "document", "path": "<path or URL>"}
```

Document IS needed for: when the user shares a file attachment, asks about a PDF/document, "read this document", "summarize this PDF", any message with a file attachment.

### Executor Update

Add to `_ACTION_TOOLS`:

```python
_ACTION_TOOLS = {
    "search": "web_search",
    "scrape": "read_page",
    "document": "read_document",
}
```

### Telegram File Handling

When a user sends a document in Telegram, the bot needs to:
1. Detect the file attachment on the incoming message
2. Download it to a temp directory (`/tmp/odigos/` or similar)
3. Include the local file path in the message metadata
4. The planner/executor uses this path to call the document tool

This requires updating `TelegramChannel` to handle `message.document` from python-telegram-bot.

### Dependencies

- `docling` in pyproject.toml
- No additional system dependencies (docling handles its own ML model downloads)

---

## Integration Points

- **`main.py`**: Initialize `DoclingProvider` and `DocTool`, register in tool registry. Pass OpenRouter provider to reflector for cost lookups.
- **`core/reflector.py`**: Spawn async cost update task after storing message.
- **`providers/openrouter.py`**: New `fetch_generation_cost()` method.
- **`providers/scraper.py`**: Replace httpx with StealthyFetcher/PlayWrightFetcher.
- **`providers/docling.py`**: New provider wrapping docling.
- **`tools/document.py`**: New tool wrapping DoclingProvider.
- **`tools/scrape.py`**: Pass tier param.
- **`core/planner.py`**: Add document action to classify prompt.
- **`core/executor.py`**: Add document to _ACTION_TOOLS map.
- **`channels/telegram.py`**: Handle file attachments, download to temp path.

What does NOT change: router, budget tracker, skill registry, context assembler, memory system, database schema.
