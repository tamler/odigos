from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from odigos.core.content_filter import ContentFilter
from odigos.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from odigos.providers.scraper import ScraperProvider

logger = logging.getLogger(__name__)

_content_filter = ContentFilter()


class ScrapeTool(BaseTool):
    """Page scraping tool -- fetches and extracts content from a URL."""

    name = "read_page"
    description = "Read and extract content from a web page URL."
    parameters_schema = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The URL to read"},
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

        result = _content_filter.scan(raw_output)
        if result.risk_level == "high":
            logger.warning(
                "Content filter: HIGH risk from %s -- patterns: %s",
                url, result.matched_patterns,
            )
            return ToolResult(success=True, data=result.sanitized_text)
        if result.risk_level == "medium":
            logger.info(
                "Content filter: MEDIUM risk from %s -- patterns: %s",
                url, result.matched_patterns,
            )
            return ToolResult(success=True, data=result.sanitized_text)

        return ToolResult(success=True, data=raw_output)
