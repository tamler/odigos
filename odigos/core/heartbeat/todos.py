"""Heartbeat todo execution module."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from odigos.channels.base import UniversalMessage
from odigos.core.heartbeat.utils import log_heartbeat_session, send_notification

if TYPE_CHECKING:
    from odigos.core.heartbeat.orchestrator import Heartbeat

logger = logging.getLogger(__name__)


async def work_todos(hb: "Heartbeat") -> bool:
    now = datetime.now(timezone.utc).isoformat()
    todos = await hb.db.fetch_all(
        "SELECT * FROM todos WHERE status = 'pending' "
        "AND (scheduled_at IS NULL OR scheduled_at <= ?) "
        "ORDER BY created_at LIMIT ?",
        (now, hb._max_todos_per_tick),
    )
    if not todos:
        return False

    for t in todos:
        await execute_todo(hb, t)
    return True


async def execute_todo(hb: "Heartbeat", todo: dict) -> None:
    todo_id = todo["id"]
    description = todo["description"] or ""
    goal_id = todo.get("goal_id")

    try:
        metadata = {"todo_id": todo_id}
        if goal_id:
            metadata["goal_id"] = goal_id
        message = UniversalMessage(
            id=str(uuid.uuid4()),
            channel="heartbeat",
            sender="system",
            content=description,
            timestamp=datetime.now(timezone.utc),
            metadata=metadata,
        )
        bg_model = getattr(hb, "background_model", "")
        todo_context = f"Todo task: {description[:200]}"
        if goal_id:
            todo_context += f"\nGoal ID: {goal_id}"

        result = await hb.agent.handle_message(
            message,
            headless=True,
            plan_context=todo_context,
            background_model=bg_model,
        )
        await hb.goal_store.complete_todo(
            todo_id, result=result[:4000] if result else None
        )
        logger.info("Todo %s completed: %s", todo_id[:8], description[:50])

        await log_heartbeat_session(
            hb,
            goal_id=goal_id,
            todo_id=todo_id,
            summary=f"Completed: {description[:200]}. Result: {(result or '')[:300]}",
        )

        if todo.get("conversation_id"):
            await send_notification(
                hb,
                todo["conversation_id"],
                f"Todo completed: {description}\n\n{result}",
            )
    except Exception as e:
        await hb.goal_store.fail_todo(todo_id, error=str(e))
        logger.error("Todo %s failed: %s", todo_id[:8], e)
        if todo.get("conversation_id"):
            await send_notification(
                hb,
                todo["conversation_id"],
                f"Todo failed: {description}\n\n{e}",
            )
