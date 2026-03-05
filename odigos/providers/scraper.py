from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

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
    """Fetches web pages and extracts clean text content."""

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
            from scrapling.parser import Adaptor

            page = Adaptor(response.text, url=url)

            # Extract title
            title = page.css("title::text").get() or ""

            # Try content-specific selectors, fall back to body
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

            # Truncate if needed
            if len(content_text) > self.max_content_chars:
                content_text = content_text[: self.max_content_chars] + "\n\n[truncated]"

            return ScrapedPage(url=url, title=title, content=content_text)

        except Exception:
            logger.warning("Failed to parse content from %s", url, exc_info=True)
            return ScrapedPage(url=url, title="", content="")

    async def close(self) -> None:
        await self._client.aclose()
