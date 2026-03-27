"""Proactive nudges: detect stale tasks, overdue goals, and follow-ups."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from odigos.db import Database

logger = logging.getLogger(__name__)

# Thresholds
STALE_TODO_HOURS = 48
STALE_PLAN_HOURS = 72
MAX_NUDGES_PER_TICK = 2
NUDGE_COOLDOWN_HOURS = 24


async def find_stale_todos(db: Database) -> list[dict]:
    """Find pending todos that haven't been touched in a while."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=STALE_TODO_HOURS)
    cutoff_str = cutoff.isoformat()

    rows = await db.fetch_all(
        """
        SELECT id, description, created_at
        FROM todos
        WHERE status = 'pending'
          AND created_at < ?
        ORDER BY created_at ASC
        LIMIT ?
        """,
        (cutoff_str, MAX_NUDGES_PER_TICK),
    )
    return [dict(r) for r in rows]


async def find_stale_plans(db: Database) -> list[dict]:
    """Find task_plans that haven't been updated in a while."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=STALE_PLAN_HOURS)
    cutoff_str = cutoff.isoformat()

    rows = await db.fetch_all(
        """
        SELECT id, conversation_id, created_at, updated_at
        FROM task_plans
        WHERE COALESCE(updated_at, created_at) < ?
        ORDER BY created_at ASC
        LIMIT ?
        """,
        (cutoff_str, MAX_NUDGES_PER_TICK),
    )
    return [dict(r) for r in rows]


async def find_overdue_goals(db: Database) -> list[dict]:
    """Find active goals that have been stale for a long time."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=STALE_PLAN_HOURS)
    cutoff_str = cutoff.isoformat()

    rows = await db.fetch_all(
        """
        SELECT id, description, created_at
        FROM goals
        WHERE status = 'active'
          AND created_at < ?
        ORDER BY created_at ASC
        LIMIT ?
        """,
        (cutoff_str, MAX_NUDGES_PER_TICK),
    )
    return [dict(r) for r in rows]


async def get_nudge_items(db: Database) -> list[dict]:
    """Collect all items worth nudging about."""
    nudges: list[dict] = []

    # Check which tables exist so we don't crash on missing tables
    tables = await db.fetch_all(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )
    table_names = {r["name"] for r in tables}

    if "todos" in table_names:
        for todo in await find_stale_todos(db):
            nudges.append({
                "type": "stale_todo",
                "id": todo["id"],
                "description": todo["description"],
                "age_hours": _hours_since(todo["created_at"]),
            })

    if "task_plans" in table_names:
        for plan in await find_stale_plans(db):
            nudges.append({
                "type": "stale_plan",
                "id": plan["id"],
                "description": (
                    plan.get("conversation_id", "Unknown plan")
                ),
                "age_hours": _hours_since(
                    plan.get("updated_at") or plan["created_at"]
                ),
            })

    if "goals" in table_names:
        for goal in await find_overdue_goals(db):
            nudges.append({
                "type": "overdue_goal",
                "id": goal["id"],
                "description": goal["description"],
                "created_at": goal["created_at"],
            })

    return nudges[:MAX_NUDGES_PER_TICK]


def format_nudge_notification(nudges: list[dict]) -> str:
    """Format nudge items into a notification message."""
    if not nudges:
        return ""

    lines = []
    for nudge in nudges:
        if nudge["type"] == "stale_todo":
            lines.append(
                f"Pending task ({int(nudge['age_hours'])}h old): "
                f"{nudge['description'][:80]}"
            )
        elif nudge["type"] == "stale_plan":
            lines.append(
                f"Stale plan ({int(nudge['age_hours'])}h): "
                f"{nudge['description'][:80]}"
            )
        elif nudge["type"] == "overdue_goal":
            age = nudge.get("age_hours")
            if age is not None:
                label = f"Stale goal ({int(age)}h)"
            else:
                created = nudge.get("created_at", "")[:10]
                label = f"Stale goal (since {created})"
            lines.append(
                f"{label}: {nudge['description'][:80]}"
            )

    return "\n".join(lines)


def _hours_since(iso_str: str) -> float:
    """Calculate hours since an ISO timestamp."""
    try:
        dt = datetime.fromisoformat(
            iso_str.replace("Z", "+00:00")
        )
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        return delta.total_seconds() / 3600
    except (ValueError, TypeError):
        return 0.0
