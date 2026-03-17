from __future__ import annotations

import ipaddress
import logging
import socket
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from odigos.tools.base import BaseTool, ToolResult
from odigos.tools.content_filter_helper import filter_external_content

if TYPE_CHECKING:
    from odigos.providers.scraper import ScraperProvider

logger = logging.getLogger(__name__)


def _is_private_url(url: str) -> bool:
    """Check if a URL resolves to a private/loopback IP address."""
    try:
        hostname = urlparse(url).hostname
        if not hostname:
            return True
        for info in socket.getaddrinfo(hostname, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                return True
    except (socket.gaierror, ValueError):
        pass
    return False


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

        if _is_private_url(url):
            return ToolResult(success=False, data="", error="Cannot scrape private or internal URLs")

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

        return filter_external_content(raw_output, url)
