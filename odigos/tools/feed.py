from __future__ import annotations

import asyncio
import logging
from functools import partial

import feedparser

from odigos.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

MAX_ENTRIES = 20


class FeedTool(BaseTool):
    """Fetch and parse RSS/Atom feeds."""

    name = "read_feed"
    description = (
        "Fetch an RSS or Atom feed and return the latest entries. "
        "Useful for monitoring news, blogs, release notes, or any public feed."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL of the RSS or Atom feed.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of entries to return (default 10, max 20).",
            },
        },
        "required": ["url"],
    }

    async def execute(self, params: dict) -> ToolResult:
        url = params.get("url", "")
        if not url:
            return ToolResult(success=False, data="", error="Missing required parameter: url")

        limit = min(int(params.get("limit", 10)), MAX_ENTRIES)

        loop = asyncio.get_running_loop()
        try:
            feed = await loop.run_in_executor(None, partial(feedparser.parse, url))
        except Exception as exc:
            return ToolResult(success=False, data="", error=f"Failed to fetch feed: {exc}")

        if feed.bozo and not feed.entries:
            error_msg = str(feed.bozo_exception) if hasattr(feed, "bozo_exception") else "Unknown"
            return ToolResult(success=False, data="", error=f"Feed parse error: {error_msg}")

        title = feed.feed.get("title", url)
        entries = feed.entries[:limit]

        if not entries:
            return ToolResult(success=True, data=f"Feed '{title}' has no entries.")

        lines = [f"## {title}\n"]
        for i, entry in enumerate(entries, 1):
            entry_title = entry.get("title", "(no title)")
            link = entry.get("link", "")
            published = entry.get("published", entry.get("updated", ""))
            summary = entry.get("summary", "")
            # Trim summary to avoid bloating context
            if len(summary) > 300:
                summary = summary[:297] + "..."

            lines.append(f"{i}. **{entry_title}**")
            if published:
                lines.append(f"   Published: {published}")
            if link:
                lines.append(f"   {link}")
            if summary:
                lines.append(f"   {summary}")
            lines.append("")

        return ToolResult(success=True, data="\n".join(lines))
