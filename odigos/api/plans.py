"""Plans API endpoint."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends

from odigos.api.deps import get_db, require_auth
from odigos.db import Database

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api",
    dependencies=[Depends(require_auth)],
)


def _count_steps(steps_json: str) -> tuple[int, int]:
    """Parse steps JSON and return (current_step, total_steps).

    current_step is the 1-indexed position of the first non-done step,
    or total_steps + 1 if everything is done.
    Returns (0, 0) if the JSON is malformed.
    """
    try:
        steps = json.loads(steps_json)
        if not isinstance(steps, list):
            return (0, 0)
    except (json.JSONDecodeError, TypeError):
        return (0, 0)

    total = len(steps)
    if total == 0:
        return (0, 0)

    done_count = 0
    for s in steps:
        if isinstance(s, dict) and s.get("status") == "done":
            done_count += 1
        else:
            break
    current = done_count + 1 if done_count < total else total
    return (current, total)


@router.get("/plans/active")
async def list_active_plans(db: Database = Depends(get_db)):
    """Return active task plans with step progress."""
    rows = await db.fetch_all(
        "SELECT id, conversation_id, goal, steps, created_at, updated_at "
        "FROM task_plans WHERE status = 'in_progress' "
        "ORDER BY updated_at DESC LIMIT 20"
    )

    plans = []
    for row in rows:
        current_step, total_steps = _count_steps(row["steps"])
        plans.append({
            "id": row["id"],
            "goal": row["goal"] or "",
            "current_step": current_step,
            "total_steps": total_steps,
            "started_at": row["created_at"],
            "updated_at": row["updated_at"],
            "conversation_id": row["conversation_id"],
        })

    return {"plans": plans}
