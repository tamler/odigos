"""Calendar tools: read events via CalDAV (Google, Apple, Outlook, Nextcloud)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from odigos.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from odigos.config import CalendarConfig

logger = logging.getLogger(__name__)


class CheckCalendarTool(BaseTool):
    name = "check_calendar"
    category = "communication"
    description = (
        "Check upcoming calendar events. Shows events for today and tomorrow by default, "
        "or a custom number of days ahead. Use this to check schedules, find free time, "
        "or remind the user about upcoming meetings."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "days_ahead": {
                "type": "integer",
                "description": "Number of days to look ahead (default: 2)",
            },
        },
    }

    def __init__(self, calendar_config: CalendarConfig) -> None:
        self._config = calendar_config

    async def execute(self, params: dict) -> ToolResult:
        if not self._config.enabled or not self._config.url:
            return ToolResult(success=False, data="", error="Calendar not configured")

        days_ahead = params.get("days_ahead", 2)

        try:
            result = await asyncio.to_thread(
                self._fetch_events, days_ahead,
            )
            return result
        except Exception as e:
            logger.warning("Calendar check failed: %s", e)
            return ToolResult(success=False, data="", error=f"Failed to check calendar: {e}")

    def _fetch_events(self, days_ahead: int) -> ToolResult:
        """Synchronous CalDAV fetch (run in thread)."""
        import caldav

        client = caldav.DAVClient(
            url=self._config.url,
            username=self._config.username,
            password=self._config.password,
        )

        try:
            principal = client.principal()
            calendars = principal.calendars()

            if not calendars:
                return ToolResult(success=True, data="No calendars found.")

            now = datetime.now(timezone.utc)
            end = now + timedelta(days=days_ahead)
            all_events = []

            for cal in calendars:
                cal_name = cal.name or "Calendar"
                try:
                    events = cal.date_search(start=now, end=end, expand=True)
                    for event in events:
                        try:
                            vevent = event.vobject_instance.vevent
                            summary = str(vevent.summary.value) if hasattr(vevent, 'summary') else "No title"
                            dtstart = vevent.dtstart.value
                            dtend = vevent.dtend.value if hasattr(vevent, 'dtend') else None
                            location = str(vevent.location.value) if hasattr(vevent, 'location') else None
                            description = str(vevent.description.value)[:200] if hasattr(vevent, 'description') else None

                            # Format time
                            if hasattr(dtstart, 'hour'):
                                start_str = dtstart.strftime("%a %b %d, %I:%M %p")
                                end_str = dtend.strftime("%I:%M %p") if dtend and hasattr(dtend, 'hour') else ""
                                time_str = f"{start_str} - {end_str}" if end_str else start_str
                            else:
                                time_str = f"{dtstart.strftime('%a %b %d')} (all day)"

                            all_events.append({
                                "summary": summary,
                                "time": time_str,
                                "calendar": cal_name,
                                "location": location,
                                "description": description,
                                "sort_key": dtstart,
                            })
                        except Exception:
                            continue
                except Exception:
                    logger.debug("Failed to search calendar %s", cal_name, exc_info=True)

            if not all_events:
                return ToolResult(success=True, data=f"No events in the next {days_ahead} day(s).")

            # Sort by start time
            all_events.sort(key=lambda e: e["sort_key"])

            lines = [f"Upcoming events ({days_ahead} days):\n"]
            for event in all_events:
                lines.append(f"**{event['summary']}**")
                lines.append(f"  {event['time']}")
                if event["location"]:
                    lines.append(f"  Location: {event['location']}")
                if event["description"]:
                    lines.append(f"  Notes: {event['description']}")
                lines.append("")

            return ToolResult(success=True, data="\n".join(lines))
        finally:
            try:
                client.close()
            except Exception:
                pass
