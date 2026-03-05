# Phase 2e Design: Page Scraping

**Date:** 2026-03-05
**Status:** Approved
**Milestone:** "It reads for me" -- the agent can fetch and read any web page on demand, extracting clean content for synthesis.

---

## Scope

On-demand page scraping using Scrapling. The agent decides which URLs to read (from search results or user messages), fetches the page, extracts content, and synthesizes an answer with the page content in context. A `scraped_pages` table logs what was read for future recall.

Deferred: browser-tier fetching (StealthyFetcher/DynamicFetcher), tag extraction, re-scrape scheduling.

### Decisions

| Decision | Choice | Reasoning |
|----------|--------|-----------|
| Library | Scrapling (`Fetcher`) | Single library covers HTTP and browser tiers. 22k stars, async, built-in parsing. Replaces httpx + trafilatura AND agent-browser. |
| Fetcher tier | `Fetcher` only (HTTP) | Lightest tier, no browser deps. Escalate to `StealthyFetcher` later (same API). |
| Integration | On-demand via tool registry | New `read_page` tool, agent decides when to scrape. Planner gets `"scrape"` action. |
| Persistence | `scraped_pages` table | Lightweight log (URL, title, summary, timestamp). Enables "what did I read about X?" recall. |
| Content limit | ~4000 chars | Fits context window without dominating it. Truncated with notice. |

---

## New Modules

```
odigos/
  providers/
    scraper.py          # Scrapling Fetcher wrapper
  tools/
    scrape.py           # Page scraping tool (BaseTool)
migrations/
  003_scraped_pages.sql # scraped_pages table
```

---

## Scraper Provider (providers/scraper.py)

Wraps Scrapling's `Fetcher` for async page fetching and content extraction:

- `scrape(url: str) -> ScrapedPage` -- fetches URL, extracts text content
- `ScrapedPage` dataclass: `url`, `title`, `content`, `scraped_at`
- Uses `Fetcher.get(url)` for HTTP fetching
- Extracts text via Scrapling's built-in `get_all_text()` or CSS-based content selection
- Content truncated to `max_content_chars` (default 4000) with truncation notice
- Graceful error handling: returns ScrapedPage with empty content and error info on failure
- No browser dependencies needed for tier 1 (`pip install scrapling`)

---

## Scrape Tool (tools/scrape.py)

Wraps the scraper provider as a `BaseTool`:
- `name = "read_page"`
- `description = "Read and extract content from a web page URL."`
- `execute({"url": "..."})` calls scraper, formats content for context injection
- Returns formatted markdown: title, URL, extracted content
- Validates URL format before fetching

---

## Page Log (migrations/003_scraped_pages.sql)

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

The reflector stores a brief entry after each scrape. Summary is the first ~200 chars of extracted content. No tags for now -- add when the agent gets categorization ability.

---

## Planner Upgrade (core/planner.py)

The classification prompt is updated to recognize URL-reading intent:
- New action: `"scrape"` with `tool_params: {"url": "<extracted_url>"}`
- Planner extracts URL from user message when user says "read this", "what does this page say", or pastes a URL
- Updated `CLASSIFY_PROMPT` adds scraping examples to the search/respond classification

---

## Executor Upgrade (core/executor.py)

Minimal change -- add `"scrape"` action handling alongside `"search"`:
- If `plan.action == "scrape"`: look up `"read_page"` tool from registry, call with URL
- Same two-pass pattern: tool executes, results injected into context, LLM synthesizes
- After successful scrape, store entry in `scraped_pages` table

---

## Reflector Upgrade (core/reflector.py)

After a scrape action, the reflector logs the page to `scraped_pages`:
- Extract URL and title from tool result
- Generate summary (first ~200 chars of content)
- Insert into `scraped_pages` table
- This enables future "what did I read about X?" queries

---

## Config Changes

None. Scrapling needs no API keys or external config. Just `pip install scrapling`.

---

## Integration Points

- **main.py**: Initialize scraper provider, create ScrapeTool, register in existing tool_registry. No new config needed.
- **planner.py**: Updated classification prompt with scrape action.
- **executor.py**: Add `"scrape"` action handling (same pattern as `"search"`).
- **reflector.py**: Log scrape results to `scraped_pages` table.
- **pyproject.toml**: Add `scrapling` dependency.

What does NOT change: context assembler, prompt builder, memory manager, personality loader, search tool, SearXNG provider.
