from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta

from odigos.db import Database

logger = logging.getLogger(__name__)


class GoalStore:
    """CRUD for goals, todos, and reminders."""

    def __init__(self, db: Database) -> None:
        self.db = db

    # --- Goals ---

    async def create_goal(self, description: str, created_by: str = "user") -> str:
        goal_id = str(uuid.uuid4())
        await self.db.execute(
            "INSERT INTO goals (id, description, created_by) VALUES (?, ?, ?)",
            (goal_id, description, created_by),
        )
        logger.info("Created goal %s: %s", goal_id[:8], description[:50])
        return goal_id

    async def list_goals(self, status: str = "active") -> list[dict]:
        return await self.db.fetch_all(
            "SELECT * FROM goals WHERE status = ? ORDER BY created_at", (status,)
        )

    async def update_goal(self, goal_id: str, **kwargs) -> bool:
        allowed = {"status", "progress_note", "reviewed_at"}
        fields = {k: v for k, v in kwargs.items() if k in allowed}
        if not fields:
            return False
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [goal_id]
        await self.db.execute(
            f"UPDATE goals SET {set_clause} WHERE id = ?", tuple(values)
        )
        return True

    # --- Todos ---

    async def create_todo(
        self,
        description: str,
        delay_seconds: int = 0,
        goal_id: str | None = None,
        conversation_id: str | None = None,
        created_by: str = "user",
    ) -> str:
        todo_id = str(uuid.uuid4())
        scheduled_at = None
        if delay_seconds > 0:
            scheduled_at = (
                datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
            ).isoformat()
        await self.db.execute(
            "INSERT INTO todos (id, description, scheduled_at, goal_id, conversation_id, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (todo_id, description, scheduled_at, goal_id, conversation_id, created_by),
        )
        logger.info("Created todo %s: %s", todo_id[:8], description[:50])
        return todo_id

    async def list_todos(self, status: str = "pending") -> list[dict]:
        return await self.db.fetch_all(
            "SELECT * FROM todos WHERE status = ? ORDER BY created_at", (status,)
        )

    async def complete_todo(self, todo_id: str, result: str | None = None) -> None:
        await self.db.execute(
            "UPDATE todos SET status = 'completed', result = ? WHERE id = ?",
            (result, todo_id),
        )

    async def fail_todo(self, todo_id: str, error: str | None = None) -> None:
        await self.db.execute(
            "UPDATE todos SET status = 'failed', error = ? WHERE id = ?",
            (error, todo_id),
        )

    # --- Reminders ---

    async def create_reminder(
        self,
        description: str,
        due_seconds: int = 0,
        recurrence: str | None = None,
        conversation_id: str | None = None,
        created_by: str = "user",
    ) -> str:
        reminder_id = str(uuid.uuid4())
        due_at = (
            datetime.now(timezone.utc) + timedelta(seconds=due_seconds)
        ).isoformat()
        await self.db.execute(
            "INSERT INTO reminders (id, description, due_at, recurrence, conversation_id, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (reminder_id, description, due_at, recurrence, conversation_id, created_by),
        )
        logger.info("Created reminder %s: %s (due: %s)", reminder_id[:8], description[:50], due_at)
        return reminder_id

    async def list_reminders(self, status: str = "pending") -> list[dict]:
        return await self.db.fetch_all(
            "SELECT * FROM reminders WHERE status = ? ORDER BY due_at", (status,)
        )

    async def cancel_reminder(self, reminder_id: str) -> bool:
        row = await self.db.fetch_one(
            "SELECT id FROM reminders WHERE id = ? AND status = 'pending'", (reminder_id,)
        )
        if not row:
            return False
        await self.db.execute(
            "UPDATE reminders SET status = 'cancelled' WHERE id = ?", (reminder_id,)
        )
        return True

    # --- Cross-table cancel ---

    async def cancel(self, item_id: str) -> bool:
        row = await self.db.fetch_one(
            "SELECT id FROM goals WHERE id = ? AND status = 'active'", (item_id,)
        )
        if row:
            await self.db.execute(
                "UPDATE goals SET status = 'archived' WHERE id = ?", (item_id,)
            )
            return True

        row = await self.db.fetch_one(
            "SELECT id FROM todos WHERE id = ? AND status = 'pending'", (item_id,)
        )
        if row:
            await self.db.execute(
                "UPDATE todos SET status = 'failed' WHERE id = ?", (item_id,)
            )
            return True

        return await self.cancel_reminder(item_id)
