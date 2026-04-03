"""Calendar tools: read, create, update, delete events via CalDAV.

Works with any CalDAV provider (Google, Apple, Outlook, Fastmail, Nextcloud).
Uses caldav 3.x with full write support.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from odigos.tools.base import BaseTool, ToolContract, ToolResult

if TYPE_CHECKING:
    from odigos.config import CalendarConfig

logger = logging.getLogger(__name__)


def _get_client(config: "CalendarConfig"):
    import caldav
    return caldav.DAVClient(url=config.url, username=config.username, password=config.password)


class CheckCalendarTool(BaseTool):
    name = "check_calendar"
    category = "communication"
    contract = ToolContract(timeout_seconds=30)
    description = (
        "Check upcoming calendar events. Shows events for the next N days. "
        "Use to check schedules, find meetings, or remind about upcoming events."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "days_ahead": {"type": "integer", "description": "Days to look ahead (default 2)"},
        },
    }

    def __init__(self, calendar_config: "CalendarConfig") -> None:
        self._config = calendar_config

    async def execute(self, params: dict) -> ToolResult:
        if not self._config.enabled or not self._config.url:
            return ToolResult(success=False, data="", error="Calendar not configured")
        params.pop("_conversation_id", None)
        params.pop("_goal_id", None)
        try:
            return await asyncio.to_thread(self._fetch, params.get("days_ahead", 2))
        except Exception as e:
            return ToolResult(success=False, data="", error=f"Calendar check failed: {e}")

    def _fetch(self, days_ahead: int) -> ToolResult:
        client = _get_client(self._config)
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
                    for event in cal.date_search(start=now, end=end, expand=True):
                        try:
                            ve = event.vobject_instance.vevent
                            summary = str(ve.summary.value) if hasattr(ve, 'summary') else "No title"
                            dtstart = ve.dtstart.value
                            dtend = ve.dtend.value if hasattr(ve, 'dtend') else None
                            location = str(ve.location.value) if hasattr(ve, 'location') else None
                            desc = str(ve.description.value)[:200] if hasattr(ve, 'description') else None
                            if hasattr(dtstart, 'hour'):
                                start_str = dtstart.strftime("%a %b %d, %I:%M %p")
                                end_str = dtend.strftime("%I:%M %p") if dtend and hasattr(dtend, 'hour') else ""
                                time_str = f"{start_str} - {end_str}" if end_str else start_str
                            else:
                                time_str = f"{dtstart.strftime('%a %b %d')} (all day)"
                            all_events.append({"summary": summary, "time": time_str, "calendar": cal_name,
                                               "location": location, "description": desc, "sort_key": dtstart})
                        except Exception:
                            continue
                except Exception:
                    pass
            if not all_events:
                return ToolResult(success=True, data=f"No events in the next {days_ahead} day(s).")
            all_events.sort(key=lambda e: e["sort_key"])
            lines = [f"Upcoming events ({days_ahead} days):\n"]
            for ev in all_events:
                lines.append(f"**{ev['summary']}**")
                lines.append(f"  {ev['time']}")
                if ev["location"]:
                    lines.append(f"  Location: {ev['location']}")
                if ev["description"]:
                    lines.append(f"  Notes: {ev['description']}")
                lines.append("")
            return ToolResult(success=True, data="\n".join(lines))
        finally:
            try:
                client.close()
            except Exception:
                pass


class CreateCalendarEventTool(BaseTool):
    name = "create_calendar_event"
    category = "communication"
    contract = ToolContract(timeout_seconds=30)
    description = (
        "Create a new calendar event via CalDAV. The event is added directly to the user's calendar. "
        "Use when the user wants to schedule a meeting, appointment, or reminder on their calendar."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Event title"},
            "start": {"type": "string", "description": "Start datetime (ISO 8601, e.g. 2026-04-15T14:00:00)"},
            "end": {"type": "string", "description": "End datetime (optional, defaults to 1 hour after start)"},
            "location": {"type": "string", "description": "Location (optional)"},
            "description": {"type": "string", "description": "Description/notes (optional)"},
            "all_day": {"type": "string", "enum": ["true", "false"], "description": "All-day event (default 'false')"},
        },
        "required": ["title", "start"],
    }

    def __init__(self, calendar_config: "CalendarConfig") -> None:
        self._config = calendar_config

    async def execute(self, params: dict) -> ToolResult:
        if not self._config.enabled or not self._config.url:
            return ToolResult(success=False, data="", error="Calendar not configured")
        params.pop("_conversation_id", None)
        params.pop("_goal_id", None)
        try:
            return await asyncio.to_thread(self._create, params)
        except Exception as e:
            return ToolResult(success=False, data="", error=f"Failed to create event: {e}")

    def _create(self, params: dict) -> ToolResult:
        from icalendar import Calendar, Event
        import secrets

        title = params.get("title", "")
        start_str = params.get("start", "")
        if not title or not start_str:
            return ToolResult(success=False, data="", error="title and start required")

        start_dt = datetime.fromisoformat(start_str)
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)

        end_str = params.get("end", "")
        if end_str:
            end_dt = datetime.fromisoformat(end_str)
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
        else:
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

        client = _get_client(self._config)
        try:
            principal = client.principal()
            calendars = principal.calendars()
            if not calendars:
                return ToolResult(success=False, data="", error="No calendars found")
            calendars[0].save_event(cal.to_ical().decode())
            return ToolResult(success=True, data=f"Event '{title}' created on {start_dt.strftime('%a %b %d, %I:%M %p')}")
        finally:
            try:
                client.close()
            except Exception:
                pass


class FindFreeTimeTool(BaseTool):
    name = "find_free_time"
    category = "communication"
    contract = ToolContract(timeout_seconds=30)
    description = (
        "Find available time slots by checking the calendar for gaps between events. "
        "Use when the user wants to schedule something and needs to find when they're free."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "days_ahead": {"type": "integer", "description": "Days to check (default 3)"},
            "min_duration_minutes": {"type": "integer", "description": "Minimum slot duration in minutes (default 30)"},
        },
    }

    def __init__(self, calendar_config: "CalendarConfig") -> None:
        self._config = calendar_config

    async def execute(self, params: dict) -> ToolResult:
        if not self._config.enabled or not self._config.url:
            return ToolResult(success=False, data="", error="Calendar not configured")
        params.pop("_conversation_id", None)
        params.pop("_goal_id", None)
        try:
            return await asyncio.to_thread(
                self._find, params.get("days_ahead", 3), params.get("min_duration_minutes", 30),
            )
        except Exception as e:
            return ToolResult(success=False, data="", error=f"Free time check failed: {e}")

    def _find(self, days_ahead: int, min_minutes: int) -> ToolResult:
        client = _get_client(self._config)
        try:
            principal = client.principal()
            calendars = principal.calendars()
            if not calendars:
                return ToolResult(success=True, data="No calendars — all time is free!")

            now = datetime.now(timezone.utc)
            end = now + timedelta(days=days_ahead)

            # Collect all event times
            busy = []
            for cal in calendars:
                try:
                    for event in cal.date_search(start=now, end=end, expand=True):
                        try:
                            ve = event.vobject_instance.vevent
                            ds = ve.dtstart.value
                            de = ve.dtend.value if hasattr(ve, 'dtend') else ds + timedelta(hours=1)
                            if hasattr(ds, 'hour'):
                                busy.append((ds, de))
                        except Exception:
                            continue
                except Exception:
                    pass

            busy.sort(key=lambda x: x[0])

            # Find gaps (business hours: 8am-6pm in event timezone or UTC)
            # Use the timezone from the first event if available, else UTC
            import zoneinfo
            try:
                first_tz = busy[0][0].tzinfo if busy else timezone.utc
            except Exception:
                first_tz = timezone.utc

            slots = []
            for day_offset in range(days_ahead):
                day = now.date() + timedelta(days=day_offset)
                day_start = datetime(day.year, day.month, day.day, 8, 0, tzinfo=first_tz)
                day_end = datetime(day.year, day.month, day.day, 18, 0, tzinfo=first_tz)

                if day_start < now:
                    day_start = now

                cursor = day_start
                for bs, be in busy:
                    if be <= cursor or bs >= day_end:
                        continue
                    if bs > cursor:
                        gap = (bs - cursor).total_seconds() / 60
                        if gap >= min_minutes:
                            slots.append((cursor, bs))
                    cursor = max(cursor, be)

                if cursor < day_end:
                    gap = (day_end - cursor).total_seconds() / 60
                    if gap >= min_minutes:
                        slots.append((cursor, day_end))

            if not slots:
                return ToolResult(success=True, data=f"No free slots of {min_minutes}+ minutes in the next {days_ahead} days.")

            lines = [f"Free time slots ({min_minutes}+ min):\n"]
            for start, end_t in slots[:15]:
                dur = int((end_t - start).total_seconds() / 60)
                lines.append(f"  {start.strftime('%a %b %d, %I:%M %p')} - {end_t.strftime('%I:%M %p')} ({dur} min)")

            return ToolResult(success=True, data="\n".join(lines))
        finally:
            try:
                client.close()
            except Exception:
                pass
