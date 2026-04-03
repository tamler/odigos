"""Feed monitoring: watch RSS/Atom feeds for relevant content."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from odigos.db import Database
from odigos.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class WatchFeedTool(BaseTool):
    name = "watch_feed"
    category = "search"
    description = (
        "Add an RSS/Atom feed to the monitored feeds list. The agent will check it "
        "periodically and surface relevant articles based on the user's interests. "
        "Provide the feed URL and optional topic filters."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "RSS/Atom feed URL"},
            "name": {"type": "string", "description": "Short name for this feed (e.g. 'TechCrunch')"},
            "topics": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional topic filters -- only surface articles matching these topics",
            },
        },
        "required": ["url", "name"],
    }

    def __init__(self, db: Database) -> None:
        self.db = db

    async def execute(self, params: dict) -> ToolResult:
        url = params.get("url", "").strip()
        name = params.get("name", "").strip()
        topics = params.get("topics", [])

        if not url or not name:
            return ToolResult(success=False, data="", error="url and name are required")

        feed_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        try:
            await self.db.execute(
                "INSERT INTO monitored_feeds (id, name, url, topics, enabled, created_at) "
                "VALUES (?, ?, ?, ?, 1, ?)",
                (feed_id, name, url, json.dumps(topics), now),
            )
        except Exception:
            # Table might not exist yet -- create it
            await self.db.execute(
                "CREATE TABLE IF NOT EXISTS monitored_feeds ("
                "id TEXT PRIMARY KEY, name TEXT NOT NULL, url TEXT NOT NULL, "
                "topics TEXT DEFAULT '[]', enabled INTEGER DEFAULT 1, "
                "last_checked_at TEXT, created_at TEXT NOT NULL)"
            )
            await self.db.execute(
                "INSERT INTO monitored_feeds (id, name, url, topics, enabled, created_at) "
                "VALUES (?, ?, ?, ?, 1, ?)",
                (feed_id, name, url, json.dumps(topics), now),
            )

        topic_text = f" (filtering for: {', '.join(topics)})" if topics else ""
        return ToolResult(
            success=True,
            data=f"Now monitoring {name}{topic_text}. I'll check it periodically and let you know about relevant articles.",
        )


class ListFeedsTool(BaseTool):
    name = "list_feeds"
    category = "search"
    description = "List all monitored RSS/Atom feeds."
    parameters_schema = {"type": "object", "properties": {}}

    def __init__(self, db: Database) -> None:
        self.db = db

    async def execute(self, params: dict) -> ToolResult:
        try:
            rows = await self.db.fetch_all(
                "SELECT name, url, topics, enabled, last_checked_at FROM monitored_feeds ORDER BY name"
            )
        except Exception as e:
            return ToolResult(
                success=False, data="", error=f"Failed to query feeds: {e}",
                failure_category="unavailable",
            )

        if not rows:
            return ToolResult(success=True, data="No monitored feeds yet. Use watch_feed to add one.")

        lines = [f"Monitoring {len(rows)} feed(s):\n"]
        for row in rows:
            status = "active" if row["enabled"] else "paused"
            topics = json.loads(row["topics"]) if row["topics"] else []
            topic_text = f" [{', '.join(topics)}]" if topics else ""
            last = row["last_checked_at"] or "never"
            lines.append(f"- **{row['name']}** ({status}){topic_text}")
            lines.append(f"  {row['url']}")
            lines.append(f"  Last checked: {last}")
            lines.append("")

        return ToolResult(success=True, data="\n".join(lines))


class CheckFeedsTool(BaseTool):
    name = "check_feeds"
    category = "search"
    description = (
        "Check all monitored feeds for new articles. Returns recent items "
        "filtered by the user's topic preferences."
        " Do not use for one-off feeds not in the monitored list — use read_feed for those."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "Max articles per feed (default: 5)"},
        },
    }

    def __init__(self, db: Database) -> None:
        self.db = db

    async def execute(self, params: dict) -> ToolResult:
        import asyncio
        limit = params.get("limit", 5)

        try:
            feeds = await self.db.fetch_all(
                "SELECT id, name, url, topics FROM monitored_feeds WHERE enabled = 1"
            )
        except Exception as e:
            return ToolResult(
                success=False, data="", error=f"Failed to query feeds: {e}",
                failure_category="unavailable",
            )

        if not feeds:
            return ToolResult(success=True, data="No monitored feeds configured. Use watch_feed to add one.")

        results = await asyncio.to_thread(self._check_all_feeds, feeds, limit)

        # Update last_checked_at
        now = datetime.now(timezone.utc).isoformat()
        for feed in feeds:
            await self.db.execute(
                "UPDATE monitored_feeds SET last_checked_at = ? WHERE id = ?",
                (now, feed["id"]),
            )

        return results

    def _check_all_feeds(self, feeds: list[dict], limit: int) -> ToolResult:
        """Synchronous feed check (run in thread)."""
        import feedparser

        all_lines = []

        for feed in feeds:
            name = feed["name"]
            url = feed["url"]
            topics = json.loads(feed["topics"]) if feed["topics"] else []

            try:
                parsed = feedparser.parse(url)
                entries = parsed.entries[:limit * 2]  # fetch extra for filtering

                if topics:
                    # Filter entries by topic keywords
                    filtered = []
                    topic_lower = [t.lower() for t in topics]
                    for entry in entries:
                        text = (entry.get("title", "") + " " + entry.get("summary", "")).lower()
                        if any(t in text for t in topic_lower):
                            filtered.append(entry)
                    entries = filtered[:limit]
                else:
                    entries = entries[:limit]

                if entries:
                    all_lines.append(f"### {name}")
                    for entry in entries:
                        title = entry.get("title", "No title")
                        link = entry.get("link", "")
                        published = entry.get("published", "")
                        summary = entry.get("summary", "")[:150]
                        all_lines.append(f"- [{title}]({link})")
                        if published:
                            all_lines.append(f"  {published}")
                        if summary:
                            all_lines.append(f"  {summary}")
                        all_lines.append("")
                else:
                    all_lines.append(f"### {name}\nNo new articles matching your topics.\n")

            except Exception as e:
                all_lines.append(f"### {name}\nFailed to check: {e}\n")

        if not all_lines:
            return ToolResult(success=True, data="No new articles from monitored feeds.")

        return ToolResult(success=True, data="\n".join(all_lines))
