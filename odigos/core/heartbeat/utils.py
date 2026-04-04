"""Utility functions for the heartbeat loop."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.core.heartbeat_old import Heartbeat

logger = logging.getLogger(__name__)


async def send_notification(hb: "Heartbeat", conversation_id: str, text: str) -> None:
    """Send a message to a conversation's channel."""
    try:
        channel = hb.channel_registry.for_conversation(conversation_id)
        if channel:
            await channel.send_message(conversation_id, text[:4000])
    except Exception:
        logger.exception("Failed to send notification")


async def log_heartbeat_session(
    hb: "Heartbeat",
    goal_id: str | None = None,
    todo_id: str | None = None,
    plan_id: str | None = None,
    conversation_id: str | None = None,
    summary: str = "",
) -> None:
    """Persist autonomous work sessions to the database across heartbeat cycles."""
    try:
        await hb.db.execute(
            "INSERT INTO heartbeat_sessions "
            "(id, goal_id, todo_id, plan_id, conversation_id, summary, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                goal_id,
                todo_id,
                plan_id,
                conversation_id,
                summary[:2000],
                datetime.now(timezone.utc).isoformat(),
            ),
        )
    except Exception:
        logger.debug("Could not log heartbeat session", exc_info=True)
