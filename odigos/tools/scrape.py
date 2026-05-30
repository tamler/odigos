from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from odigos.security.events import log_security_event
from odigos.tools.base import BaseTool, ToolResult
from odigos.tools.content_filter_helper import filter_external_content
from odigos.tools.url_guard import is_blocked_url

if TYPE_CHECKING:
    from odigos.providers.scraper import ScraperProvider

logger = logging.getLogger(__name__)


class ScrapeTool(BaseTool):
    """Page scraping tool -- fetches and extracts content from a URL."""

    name = "read_page"
    category = "search"
    description = "Fetch and read the full content of a specific web page by URL. Use when you have a URL and need its content. Do not use for general topic searches — use web_search instead."
    parameters_schema = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The URL to read"},
            "tier": {"type": "string", "enum": ["standard", "js"], "description": "Rendering mode: standard for static pages, js for JavaScript-heavy SPAs. Default: standard."},
        },
        "required": ["url"],
    }

    def __init__(self, scraper: ScraperProvider) -> None:
        self.scraper = scraper

    async def execute(self, params: dict) -> ToolResult:
        url = params.get("url", "")
        tier = params.get("tier", "standard")
        if not url:
            return ToolResult(success=False, data="", error="No URL provided")

        if is_blocked_url(url):
            log_security_event("ssrf_blocked", url)
            return ToolResult(success=False, data="", error="Cannot scrape private or internal URLs")

        # Redirects/subresources are followed inside the fetcher; host egress firewall (C0 checklist) is the backstop.

        page = await self.scraper.scrape(url, tier=tier)

        if not page.content:
            return ToolResult(
                success=True,
                data=f"Could not extract content from {url}.",
            )

        lines = [f"## Page: {page.title or page.url}\n"]
        lines.append(f"**URL:** {page.url}\n")
        lines.append(page.content)

        raw_output = "\n".join(lines)

        # Archive source content to data/sources/
        try:
            from odigos.memory.brain_writer import BrainWriter
            await BrainWriter().write_source(
                content=page.content,
                title=page.title or url,
                url=url,
                content_type="web_page",
            )
        except Exception:
            logger.debug("Source archival failed for %s", url)

        return filter_external_content(raw_output, url)
