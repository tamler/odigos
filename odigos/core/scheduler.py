"""Unified scheduler for one-shot and recurring tasks."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from odigos.core.cron import CronExpression

if TYPE_CHECKING:
    from odigos.db import Database

logger = logging.getLogger(__name__)


class Scheduler:
    """Unified scheduling for one-shot and recurring tasks.

    Stores everything in the ``scheduled_tasks`` table.  One-shot tasks
    (type='once') fire once and are disabled.  Recurring tasks
    (type='recurring') use a cron expression and auto-advance.
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    async def schedule_once(
        self,
        name: str,
        action: str,
        scheduled_time: str | datetime,
        action_type: str = "remind",
        goal_id: str | None = None,
        conversation_id: str | None = None,
    ) -> str:
        """Schedule a one-shot task.

        ``scheduled_time`` can be an ISO datetime string or a datetime object.
        """
        if isinstance(scheduled_time, datetime):
            scheduled_time = scheduled_time.isoformat()

        task_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        await self.db.execute(
            "INSERT INTO scheduled_tasks "
            "(id, name, type, schedule, action, action_type, conversation_id, goal_id, "
            "enabled, last_run_at, next_run_at, created_at) "
            "VALUES (?, ?, 'once', ?, ?, ?, ?, ?, 1, NULL, ?, ?)",
            (
                task_id,
                name,
                scheduled_time,
                action,
                action_type,
                conversation_id,
                goal_id,
                scheduled_time,
                now,
            ),
        )
        logger.info("Scheduled one-shot task %s: %s (at %s)", task_id[:8], name, scheduled_time)
        return task_id

    async def schedule_recurring(
        self,
        name: str,
        action: str,
        cron_expression: str,
        action_type: str = "execute",
        conversation_id: str | None = None,
    ) -> str:
        """Schedule a recurring task with a cron expression."""
        expr = CronExpression(cron_expression)  # raises ValueError if invalid
        now = datetime.now(timezone.utc)
        task_id = str(uuid.uuid4())
        next_run = expr.next_from(now).isoformat()

        await self.db.execute(
            "INSERT INTO scheduled_tasks "
            "(id, name, type, schedule, action, action_type, conversation_id, goal_id, "
            "enabled, last_run_at, next_run_at, created_at) "
            "VALUES (?, ?, 'recurring', ?, ?, ?, ?, NULL, 1, NULL, ?, ?)",
            (
                task_id,
                name,
                cron_expression,
                action,
                action_type,
                conversation_id,
                next_run,
                now.isoformat(),
            ),
        )
        logger.info("Scheduled recurring task %s: %s (%s)", task_id[:8], name, cron_expression)
        return task_id

    async def list_tasks(self, enabled_only: bool = False) -> list[dict]:
        """List all scheduled tasks."""
        if enabled_only:
            rows = await self.db.fetch_all(
                "SELECT * FROM scheduled_tasks WHERE enabled = 1 ORDER BY created_at"
            )
        else:
            rows = await self.db.fetch_all(
                "SELECT * FROM scheduled_tasks ORDER BY created_at"
            )
        return [dict(r) for r in rows]

    async def cancel(self, task_id: str) -> None:
        """Cancel/delete a scheduled task."""
        await self.db.execute("DELETE FROM scheduled_tasks WHERE id = ?", (task_id,))

    async def toggle(self, task_id: str, enabled: bool) -> None:
        """Enable/disable a task."""
        if enabled:
            row = await self.db.fetch_one(
                "SELECT type, schedule FROM scheduled_tasks WHERE id = ?", (task_id,)
            )
            if row and row["type"] == "recurring":
                expr = CronExpression(row["schedule"])
                next_run = expr.next_from(datetime.now(timezone.utc)).isoformat()
                await self.db.execute(
                    "UPDATE scheduled_tasks SET enabled = 1, next_run_at = ? WHERE id = ?",
                    (next_run, task_id),
                )
            else:
                await self.db.execute(
                    "UPDATE scheduled_tasks SET enabled = 1 WHERE id = ?",
                    (task_id,),
                )
        else:
            await self.db.execute(
                "UPDATE scheduled_tasks SET enabled = 0 WHERE id = ?",
                (task_id,),
            )

    async def get_due_tasks(self) -> list[dict]:
        """Get tasks due to run now (next_run_at <= now, enabled)."""
        now = datetime.now(timezone.utc).isoformat()
        rows = await self.db.fetch_all(
            "SELECT * FROM scheduled_tasks WHERE enabled = 1 AND next_run_at <= ? "
            "ORDER BY next_run_at",
            (now,),
        )
        return [dict(r) for r in rows]

    async def mark_completed(self, task_id: str) -> None:
        """Mark a task as run.

        For recurring tasks, compute the next ``next_run_at``.
        For one-shot tasks, disable the task.
        """
        now = datetime.now(timezone.utc)
        row = await self.db.fetch_one(
            "SELECT type, schedule FROM scheduled_tasks WHERE id = ?", (task_id,)
        )
        if not row:
            return

        if row["type"] == "recurring":
            expr = CronExpression(row["schedule"])
            next_run = expr.next_from(now).isoformat()
            await self.db.execute(
                "UPDATE scheduled_tasks SET last_run_at = ?, next_run_at = ? WHERE id = ?",
                (now.isoformat(), next_run, task_id),
            )
        else:
            # One-shot: mark as run and disable
            await self.db.execute(
                "UPDATE scheduled_tasks SET last_run_at = ?, enabled = 0 WHERE id = ?",
                (now.isoformat(), task_id),
            )
