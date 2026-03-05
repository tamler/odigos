from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone, timedelta

from odigos.db import Database

logger = logging.getLogger(__name__)


class TaskScheduler:
    """Central task CRUD. Any component can create/query/cancel tasks."""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def create(
        self,
        description: str,
        delay_seconds: int = 0,
        recurrence_seconds: int | None = None,
        priority: int = 1,
        conversation_id: str | None = None,
        created_by: str = "user",
        payload: dict | None = None,
    ) -> str:
        task_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        scheduled_at = (now + timedelta(seconds=delay_seconds)).isoformat()
        task_type = "recurring" if recurrence_seconds else "one_shot"
        recurrence_json = (
            json.dumps({"interval_seconds": recurrence_seconds})
            if recurrence_seconds
            else None
        )
        payload_json = json.dumps(payload) if payload else None

        await self.db.execute(
            "INSERT INTO tasks (id, type, status, description, payload_json, "
            "scheduled_at, priority, recurrence_json, conversation_id, created_by) "
            "VALUES (?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?)",
            (
                task_id,
                task_type,
                description,
                payload_json,
                scheduled_at,
                priority,
                recurrence_json,
                conversation_id,
                created_by,
            ),
        )
        logger.info("Created task %s: %s (scheduled: %s)", task_id, description, scheduled_at)
        return task_id

    async def cancel(self, task_id: str) -> bool:
        row = await self.db.fetch_one(
            "SELECT id FROM tasks WHERE id = ? AND status = 'pending'", (task_id,)
        )
        if not row:
            return False
        await self.db.execute(
            "UPDATE tasks SET status = 'cancelled' WHERE id = ?", (task_id,)
        )
        logger.info("Cancelled task %s", task_id)
        return True

    async def list_pending(self, limit: int = 20) -> list[dict]:
        return await self.db.fetch_all(
            "SELECT * FROM tasks WHERE status = 'pending' "
            "ORDER BY priority ASC, scheduled_at ASC LIMIT ?",
            (limit,),
        )

    async def get(self, task_id: str) -> dict | None:
        return await self.db.fetch_one(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        )
