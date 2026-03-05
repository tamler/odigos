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
