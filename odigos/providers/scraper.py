from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from scrapling.fetchers import StealthyFetcher, DynamicFetcher

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
        - "browser": DynamicFetcher (full browser rendering for JS-heavy sites)
    """

    def __init__(self, max_content_chars: int = 4000) -> None:
        self.max_content_chars = max_content_chars

    async def scrape(self, url: str, tier: str = "standard") -> ScrapedPage:
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
        if tier == "browser":
            return DynamicFetcher.fetch(url)
        return StealthyFetcher.fetch(url)

    async def close(self) -> None:
        pass
