"""Idle research: agent works on open questions during downtime."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from odigos.db import Database

logger = logging.getLogger(__name__)


async def find_research_opportunities(
    db: Database,
) -> list[dict]:
    """Find open questions or incomplete research from
    recent conversations."""
    tables = await db.fetch_all(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )
    table_names = {r["name"] for r in tables}

    opportunities: list[dict] = []

    # 1. Find incomplete plans that could use background work
    if "task_plans" in table_names:
        rows = await db.fetch_all(
            """
            SELECT id, goal, created_at
            FROM task_plans
            WHERE status = 'in_progress'
            ORDER BY created_at DESC
            LIMIT 3
            """,
        )
        for row in rows:
            opportunities.append({
                "type": "incomplete_plan",
                "id": row["id"],
                "description": row.get("goal", "")[:200],
            })

    # 2. Find recent user questions the agent couldn't fully answer
    if "messages" in table_names:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=48)
        ).isoformat()
        rows = await db.fetch_all(
            """
            SELECT m1.content as question, m2.content as answer,
                   m1.conversation_id, m1.created_at
            FROM messages m1
            LEFT JOIN messages m2
                ON m2.conversation_id = m1.conversation_id
                AND m2.role = 'assistant'
                AND m2.created_at > m1.created_at
            WHERE m1.role = 'user'
              AND m1.created_at > ?
              AND m1.content LIKE '%?%'
              AND (
                  m2.content IS NULL
                  OR LENGTH(m2.content) < 100
              )
            ORDER BY m1.created_at DESC
            LIMIT 3
            """,
            (cutoff,),
        )
        for row in rows:
            if row["question"]:
                opportunities.append({
                    "type": "unanswered_question",
                    "description": row["question"][:200],
                    "conversation_id": (
                        row["conversation_id"]
                    ),
                })

    return opportunities[:3]


def format_research_prompt(
    opportunities: list[dict],
) -> str:
    """Format research opportunities into an LLM prompt."""
    if not opportunities:
        return ""

    lines = [
        "During idle time, consider researching"
        " these open items:"
    ]
    for opp in opportunities:
        if opp["type"] == "incomplete_plan":
            lines.append(
                f"- Plan in progress: {opp['description']}"
            )
        elif opp["type"] == "unanswered_question":
            lines.append(
                "- Unanswered question:"
                f" {opp['description']}"
            )

    return "\n".join(lines)
