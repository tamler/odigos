"""Scheduled task functions for the heartbeat loop."""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from odigos.channels.base import UniversalMessage

if TYPE_CHECKING:
    from odigos.core.heartbeat.orchestrator import Heartbeat

logger = logging.getLogger(__name__)


async def maybe_send_briefing(hb: "Heartbeat") -> None:
    """Send morning briefing once per day if enabled."""
    try:
        if hb.settings:
            enabled = hb.settings.heartbeat.morning_briefing
            if not enabled:
                return

        from odigos.core.briefing import should_send_briefing, compose_briefing, mark_briefing_sent

        if not await should_send_briefing(hb.db):
            return

        logger.info("Composing morning briefing")
        content = await compose_briefing(
            hb.db, hb.provider, settings=hb.settings, intelligence="background",
        )

        if hb.notifier:
            await hb.notifier.notify(
                title="Morning Briefing",
                body=content,
            )

        web_channel = hb.channel_registry.get("web") if hb.channel_registry else None
        if web_channel and hasattr(web_channel, 'broadcast'):
            await web_channel.broadcast({
                "type": "morning_briefing",
                "content": content,
            })

        await mark_briefing_sent(hb.db)
        logger.info("Morning briefing sent")
    except Exception:
        logger.debug("Morning briefing failed", exc_info=True)


async def process_scheduled_tasks(hb: "Heartbeat") -> bool:
    """Process due tasks from the unified scheduled_tasks table."""
    from odigos.core.heartbeat.utils import send_notification

    if not hb.scheduler:
        return False
    due_tasks = await hb.scheduler.get_due_tasks()
    if not due_tasks:
        return False

    for task in due_tasks:
        try:
            action_type = task.get("action_type", "remind")
            if action_type == "remind":
                if hb.notifier:
                    await hb.notifier.notify(
                        title="Reminder",
                        body=task["action"],
                        conversation_id=task.get("conversation_id"),
                    )
                elif task.get("conversation_id"):
                    await send_notification(
                        hb,
                        task["conversation_id"],
                        f"Reminder: {task['action']}",
                    )
            elif action_type == "execute":
                message = UniversalMessage(
                    id=str(uuid.uuid4()),
                    channel="scheduler",
                    sender="system",
                    content=task["action"],
                    timestamp=datetime.now(timezone.utc),
                    metadata={
                        "scheduled_task_id": task["id"],
                        "scheduled_task_name": task["name"],
                    },
                )
                result = await hb.agent.handle_message(message)
                if hb.notifier:
                    await hb.notifier.notify(
                        title=f"Scheduled: {task['name']}",
                        body=result[:4000] if result else "(no output)",
                        conversation_id=task.get("conversation_id"),
                    )
            elif action_type == "notify":
                if hb.notifier:
                    await hb.notifier.notify(
                        title="Scheduled",
                        body=task["action"],
                        conversation_id=task.get("conversation_id"),
                    )
                elif task.get("conversation_id"):
                    await send_notification(
                        hb,
                        task["conversation_id"],
                        task["action"],
                    )
        except Exception:
            logger.exception(
                "Scheduled task '%s' (%s) failed", task["name"], task["id"][:8]
            )

        await hb.scheduler.mark_completed(task["id"])
        logger.info(
            "Processed scheduled task '%s' (type=%s, action_type=%s)",
            task["name"], task["type"], task.get("action_type", "remind"),
        )
    return True


async def fire_reminders(hb: "Heartbeat") -> bool:
    """Fire pending reminders that are due."""
    from odigos.core.heartbeat.utils import send_notification

    now = datetime.now(timezone.utc).isoformat()
    reminders = await hb.db.fetch_all(
        "SELECT * FROM reminders WHERE status = 'pending' AND due_at <= ? "
        "ORDER BY due_at LIMIT 10",
        (now,),
    )
    if not reminders:
        return False

    for r in reminders:
        await hb.db.execute(
            "UPDATE reminders SET status = 'fired' WHERE id = ?", (r["id"],)
        )
        if r.get("conversation_id"):
            await send_notification(
                hb, r["conversation_id"], f"Reminder: {r['description']}"
            )
        if r.get("recurrence"):
            await reinsert_recurring_reminder(hb, r)
        logger.info("Fired reminder %s: %s", r["id"][:8], r["description"][:50])
    return True


async def reinsert_recurring_reminder(hb: "Heartbeat", reminder: dict) -> None:
    """Reinsert a recurring reminder after it fires."""
    recurrence = reminder.get("recurrence", "")
    interval = parse_recurrence_seconds(recurrence)
    await hb.goal_store.create_reminder(
        description=reminder["description"],
        due_seconds=interval,
        recurrence=recurrence,
        conversation_id=reminder.get("conversation_id"),
        created_by="heartbeat",
    )


def parse_recurrence_seconds(recurrence: str) -> int:
    """Parse a recurrence string into seconds until next occurrence.

    Supports: 'daily', 'weekly', 'hourly', 'every Ns', and natural
    language like 'every 2 hours', 'every 30 minutes', 'every 3 days'.
    Falls back to 3600 (1 hour) for unrecognized patterns.
    """
    from dateutil.relativedelta import relativedelta

    simple = {"daily": 86400, "weekly": 604800, "hourly": 3600}
    if recurrence in simple:
        return simple[recurrence]

    # "every Ns" — raw seconds
    if recurrence.startswith("every ") and recurrence.endswith("s"):
        try:
            return int(recurrence[6:-1])
        except ValueError:
            pass

    # Natural language: "every N unit(s)"
    match = re.match(r"every\s+(\d+)\s+(\w+)", recurrence, re.IGNORECASE)
    if match:
        count = int(match.group(1))
        unit = match.group(2).lower().rstrip("s")  # normalize plural
        unit_map = {"second": 1, "minute": 60, "hour": 3600, "day": 86400, "week": 604800}
        if unit in unit_map:
            return count * unit_map[unit]
        # Use relativedelta for month-level intervals
        if unit == "month":
            delta = relativedelta(months=count)
            now = datetime.now(timezone.utc)
            future = now + delta
            return int((future - now).total_seconds())

    return 3600
