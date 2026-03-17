"""Analytics API -- query classification stats, skill usage, task plans, tool errors."""

import json

from fastapi import APIRouter, Depends

from odigos.api.deps import get_db, require_auth
from odigos.db import Database

router = APIRouter(
    prefix="/api/analytics",
    dependencies=[Depends(require_auth)],
)


@router.get("/classifications")
async def get_classifications(db: Database = Depends(get_db)):
    """Return classification stats from query_log over the last 7 days."""
    rows = await db.fetch_all(
        "SELECT classification, COUNT(*) as count, "
        "AVG(evaluation_score) as avg_score, "
        "AVG(duration_ms) as avg_duration, "
        "AVG(CASE WHEN classifier_tier IS NOT NULL THEN classifier_confidence END) as avg_confidence "
        "FROM query_log "
        "WHERE created_at > datetime('now', '-7 days') "
        "GROUP BY classification ORDER BY count DESC"
    )
    classifications = [dict(r) for r in rows]
    total = sum(c["count"] for c in classifications)
    return {"classifications": classifications, "total_queries": total}


@router.get("/skills")
async def get_skills(db: Database = Depends(get_db)):
    """Return skill usage stats over the last 7 days."""
    rows = await db.fetch_all(
        "SELECT skill_name, skill_type, COUNT(*) as count, "
        "AVG(evaluation_score) as avg_score "
        "FROM skill_usage "
        "WHERE created_at > datetime('now', '-7 days') "
        "GROUP BY skill_name ORDER BY count DESC"
    )
    skills = [dict(r) for r in rows]
    total = sum(s["count"] for s in skills)
    return {"skills": skills, "total_uses": total}


@router.get("/errors")
async def get_errors(db: Database = Depends(get_db)):
    """Return recent tool errors grouped by tool and error type."""
    rows = await db.fetch_all(
        "SELECT tool_name, error_type, COUNT(*) as count, "
        "MAX(created_at) as last_occurrence "
        "FROM tool_errors "
        "WHERE created_at > datetime('now', '-7 days') "
        "GROUP BY tool_name, error_type ORDER BY count DESC"
    )
    return {"errors": [dict(r) for r in rows]}


@router.get("/plans")
async def get_plans(db: Database = Depends(get_db)):
    """Return active and recent task plans with step completion stats."""
    rows = await db.fetch_all(
        "SELECT id, conversation_id, steps, created_at, updated_at "
        "FROM task_plans ORDER BY updated_at DESC LIMIT 20"
    )
    plans = []
    for r in rows:
        row_dict = dict(r)
        try:
            steps = json.loads(row_dict["steps"])
        except (json.JSONDecodeError, TypeError):
            steps = []
        steps_total = len(steps)
        steps_done = sum(1 for s in steps if s.get("status") == "done")
        plans.append({
            "id": row_dict["id"],
            "conversation_id": row_dict["conversation_id"],
            "steps_total": steps_total,
            "steps_done": steps_done,
            "created_at": row_dict["created_at"],
            "updated_at": row_dict["updated_at"],
        })
    return {"plans": plans}


@router.get("/overview")
async def get_overview(db: Database = Depends(get_db)):
    """Combined overview for dashboards -- all key stats in one call."""
    query_row = await db.fetch_one(
        "SELECT COUNT(*) as cnt FROM query_log "
        "WHERE created_at > datetime('now', '-7 days')"
    )
    skill_row = await db.fetch_one(
        "SELECT COUNT(*) as cnt FROM skill_usage "
        "WHERE created_at > datetime('now', '-7 days')"
    )
    error_row = await db.fetch_one(
        "SELECT COUNT(*) as cnt FROM tool_errors "
        "WHERE created_at > datetime('now', '-7 days')"
    )
    plan_row = await db.fetch_one(
        "SELECT COUNT(*) as cnt FROM task_plans"
    )
    profile_row = await db.fetch_one(
        "SELECT last_analyzed_at FROM user_profile WHERE id = 'owner'"
    )
    return {
        "total_queries_7d": query_row["cnt"] if query_row else 0,
        "total_skill_uses_7d": skill_row["cnt"] if skill_row else 0,
        "total_errors_7d": error_row["cnt"] if error_row else 0,
        "active_plans": plan_row["cnt"] if plan_row else 0,
        "user_profile_last_analyzed": (
            profile_row["last_analyzed_at"] if profile_row else None
        ),
    }
