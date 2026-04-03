"""Calendar event (.ics) file generation tool."""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from pathlib import Path

from odigos.storage import FILES_DIR
from odigos.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class CalendarEventTool(BaseTool):
    """Generate downloadable .ics calendar event files."""

    name = "create_calendar_event"
    category = "create"
    description = (
        "Create a downloadable .ics calendar event file that the user can import "
        "into any calendar app (Apple Calendar, Google Calendar, Outlook). "
        "Use when the user wants a calendar event they can add to their calendar. "
        "Do not use if the user's calendar is connected via CalDAV — use check_calendar instead."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Event title/summary.",
            },
            "start": {
                "type": "string",
                "description": "Start date/time in ISO 8601 format (e.g. '2026-04-15T14:00:00').",
            },
            "end": {
                "type": "string",
                "description": "End date/time in ISO 8601 format. If omitted, defaults to 1 hour after start.",
            },
            "location": {
                "type": "string",
                "description": "Event location (optional).",
            },
            "description": {
                "type": "string",
                "description": "Event description/notes (optional).",
            },
            "all_day": {
                "type": "string",
                "enum": ["true", "false"],
                "description": "Whether this is an all-day event (default 'false').",
            },
        },
        "required": ["title", "start"],
    }

    def __init__(self, db=None):
        self._db = db

    async def execute(self, params: dict) -> ToolResult:
        title = params.get("title", "").strip()
        start_str = params.get("start", "").strip()
        params.pop("_conversation_id", None)
        params.pop("_goal_id", None)

        if not title or not start_str:
            return ToolResult(success=False, data="", error="title and start required")

        try:
            from icalendar import Calendar, Event
            import pytz
        except ImportError:
            return ToolResult(success=False, data="", error="icalendar library not installed")

        try:
            start_dt = datetime.fromisoformat(start_str)
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)

            end_str = params.get("end", "")
            if end_str:
                end_dt = datetime.fromisoformat(end_str)
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=timezone.utc)
            else:
                from datetime import timedelta
                end_dt = start_dt + timedelta(hours=1)

            cal = Calendar()
            cal.add("prodid", "-//Odigos//Agent//EN")
            cal.add("version", "2.0")

            event = Event()
            event.add("summary", title)

            all_day = str(params.get("all_day", "false")).lower() == "true"
            if all_day:
                event.add("dtstart", start_dt.date())
                event.add("dtend", end_dt.date())
            else:
                event.add("dtstart", start_dt)
                event.add("dtend", end_dt)

            if params.get("location"):
                event.add("location", params["location"])
            if params.get("description"):
                event.add("description", params["description"])

            event.add("uid", f"{secrets.token_hex(16)}@odigos")
            event.add("dtstamp", datetime.now(timezone.utc))

            cal.add_component(event)

            FILES_DIR.mkdir(parents=True, exist_ok=True)
            file_id = secrets.token_hex(8)
            safe_title = "".join(c if c.isalnum() or c in "-_ " else "" for c in title)[:30].strip()
            filename = f"{safe_title}_{file_id}.ics"
            filepath = FILES_DIR / filename
            filepath.write_bytes(cal.to_ical())

            file_size = filepath.stat().st_size

            if self._db:
                now = datetime.now(timezone.utc).isoformat()
                await self._db.execute(
                    "INSERT OR IGNORE INTO artifacts "
                    "(id, filename, content_type, file_size, file_path, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (file_id, filename, "text/calendar", file_size, str(filepath), now),
                )

            return ToolResult(
                success=True,
                data=f"Calendar event created: {title} on {start_dt.strftime('%Y-%m-%d %H:%M')}",
                side_effect={
                    "artifact": {
                        "id": file_id,
                        "filename": filename,
                        "content_type": "text/calendar",
                        "file_size": file_size,
                        "download_url": f"/api/artifacts/{file_id}/download",
                    },
                },
            )
        except Exception as e:
            return ToolResult(success=False, data="", error=str(e))
