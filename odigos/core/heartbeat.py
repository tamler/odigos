from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from odigos.channels.base import UniversalMessage
from odigos.db import Database

if TYPE_CHECKING:
    from odigos.channels.telegram import TelegramChannel
    from odigos.core.agent import Agent
    from odigos.core.scheduler import TaskScheduler

logger = logging.getLogger(__name__)


class Heartbeat:
    """Background loop that executes scheduled tasks."""

    def __init__(
        self,
        db: Database,
        agent: Agent,
        telegram_channel: TelegramChannel,
        scheduler: TaskScheduler,
        interval: float = 30,
        max_tasks_per_tick: int = 5,
    ) -> None:
        self.db = db
        self.agent = agent
        self.telegram_channel = telegram_channel
        self.scheduler = scheduler
        self._interval = interval
        self._max_tasks_per_tick = max_tasks_per_tick
        self._task: asyncio.Task | None = None
        self.paused: bool = False

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())
        logger.info("Heartbeat started (interval: %.1fs)", self._interval)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            logger.info("Heartbeat stopped")

    async def _loop(self) -> None:
        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Heartbeat tick failed")
            await asyncio.sleep(self._interval)

    async def _tick(self) -> None:
        if self.paused:
            return

        now = datetime.now(timezone.utc).isoformat()
        tasks = await self.db.fetch_all(
            "SELECT * FROM tasks WHERE status = 'pending' "
            "AND (scheduled_at IS NULL OR scheduled_at <= ?) "
            "ORDER BY priority ASC, scheduled_at ASC LIMIT ?",
            (now, self._max_tasks_per_tick),
        )

        for task in tasks:
            await self._execute_task(task)

    async def _execute_task(self, task: dict) -> None:
        task_id = task["id"]
        description = task["description"] or ""

        await self.db.execute(
            "UPDATE tasks SET status = 'running', started_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), task_id),
        )

        try:
            message = UniversalMessage(
                id=str(uuid.uuid4()),
                channel="heartbeat",
                sender="system",
                content=description,
                timestamp=datetime.now(timezone.utc),
                metadata={"task_id": task_id},
            )

            result = await self.agent.handle_message(message)

            await self.db.execute(
                "UPDATE tasks SET status = 'completed', completed_at = ?, "
                "result_json = ? WHERE id = ?",
                (
                    datetime.now(timezone.utc).isoformat(),
                    result[:4000] if result else None,
                    task_id,
                ),
            )
            logger.info("Task %s completed: %s", task_id, description[:50])

            if task.get("conversation_id"):
                await self._send_result(task["conversation_id"], description, result)

            if task.get("recurrence_json"):
                await self._reinsert_recurring(task)

        except Exception as e:
            retry_count = (task.get("retry_count") or 0) + 1
            max_retries = task.get("max_retries") or 3

            if retry_count >= max_retries:
                await self.db.execute(
                    "UPDATE tasks SET status = 'failed', error = ?, retry_count = ? WHERE id = ?",
                    (str(e), retry_count, task_id),
                )
                logger.error("Task %s failed permanently after %d retries: %s", task_id, retry_count, e)
                if task.get("conversation_id"):
                    await self._send_result(
                        task["conversation_id"],
                        description,
                        f"Task failed after {retry_count} attempts: {e}",
                        failed=True,
                    )
            else:
                await self.db.execute(
                    "UPDATE tasks SET status = 'pending', error = ?, retry_count = ? WHERE id = ?",
                    (str(e), retry_count, task_id),
                )
                logger.warning("Task %s failed (attempt %d/%d): %s", task_id, retry_count, max_retries, e)

    async def _send_result(
        self, conversation_id: str, description: str, result: str, *, failed: bool = False,
    ) -> None:
        try:
            parts = conversation_id.split(":", 1)
            if len(parts) == 2 and parts[0] == "telegram":
                chat_id = int(parts[1])
                prefix = "Task failed" if failed else "Task completed"
                message = f"{prefix}: {description}\n\n{result}"
                await self.telegram_channel.send_message(chat_id, message[:4000])
        except Exception:
            logger.exception("Failed to send task result via Telegram")

    async def _reinsert_recurring(self, task: dict) -> None:
        recurrence = json.loads(task["recurrence_json"])
        interval = recurrence.get("interval_seconds", 3600)
        await self.scheduler.create(
            description=task["description"],
            delay_seconds=interval,
            recurrence_seconds=interval,
            priority=task.get("priority", 1),
            conversation_id=task.get("conversation_id"),
            created_by="heartbeat",
        )
