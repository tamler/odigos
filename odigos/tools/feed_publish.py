"""Tool for publishing entries to the agent's RSS feed."""
from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING

from odigos.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from odigos.db import Database


class PublishToFeedTool(BaseTool):
    name = "publish_to_feed"
    description = (
        "Publish an entry to your RSS feed. Subscribers with subscribe cards "
        "will see this in their feed reader."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Title of the feed entry",
            },
            "content": {
                "type": "string",
                "description": "Content/body of the feed entry",
            },
            "category": {
                "type": "string",
                "description": "Optional category (e.g., research, alert, status, digest)",
            },
        },
        "required": ["title", "content"],
    }

    def __init__(self, db: Database, feed_base_url: str = "") -> None:
        self.db = db
        self.feed_base_url = feed_base_url

    async def execute(self, params: dict) -> ToolResult:
        title = params.get("title")
        content = params.get("content")
        category = params.get("category")

        if not title:
            return ToolResult(success=False, data="", error="Missing required parameter: title")
        if not content:
            return ToolResult(success=False, data="", error="Missing required parameter: content")

        entry_id = str(uuid.uuid4())
        await self.db.execute(
            "INSERT INTO feed_entries (id, title, content, category) VALUES (?, ?, ?, ?)",
            (entry_id, title, content, category),
        )

        feed_url = f"{self.feed_base_url}/feed.xml" if self.feed_base_url else "/feed.xml"

        return ToolResult(
            success=True,
            data=json.dumps({
                "id": entry_id,
                "title": title,
                "feed_url": feed_url,
            }),
        )
