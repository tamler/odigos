"""Shared database query helpers to eliminate duplication."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.db import Database


async def get_recent_tool_errors(db: Database, days: int = 1) -> list[dict]:
    """Get tool errors grouped by tool/type from the last N days."""
    rows = await db.fetch_all(
        "SELECT tool_name, error_type, COUNT(*) as count "
        "FROM tool_errors WHERE created_at > datetime('now', ? || ' days') "
        "GROUP BY tool_name, error_type ORDER BY count DESC",
        (f"-{days}",),
    )
    return [dict(r) for r in rows] if rows else []


async def get_user_profile(db: Database) -> dict | None:
    """Get the owner's user profile."""
    row = await db.fetch_one(
        "SELECT communication_style, expertise_areas, preferences, "
        "recurring_topics, summary FROM user_profile WHERE id = 'owner'"
    )
    return dict(row) if row else None


async def get_user_facts(db: Database, limit: int = 20) -> list[dict]:
    """Get user facts ordered by confidence and recency."""
    rows = await db.fetch_all(
        "SELECT fact, category FROM user_facts "
        "ORDER BY confidence DESC, updated_at DESC LIMIT ?",
        (limit,),
    )
    return [dict(r) for r in rows] if rows else []
