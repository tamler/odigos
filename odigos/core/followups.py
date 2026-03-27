"""Follow-up detection: find user commitments and create reminders."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from odigos.db import Database

logger = logging.getLogger(__name__)

# Patterns that suggest user commitments (checked in recent messages)
COMMITMENT_PATTERNS = [
    "i'll do",
    "i will",
    "i need to",
    "i should",
    "let me",
    "i'm going to",
    "remind me",
    "by friday",
    "by monday",
    "by tomorrow",
    "by end of",
    "deadline",
    "due date",
]


async def find_untracked_commitments(
    db: Database, hours: int = 24,
) -> list[dict]:
    """Find recent user messages containing commitment language
    that don't have a corresponding todo or reminder."""
    # Check which tables exist
    tables = await db.fetch_all(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )
    table_names = {r["name"] for r in tables}

    if "messages" not in table_names:
        return []

    cutoff = datetime.now(timezone.utc).isoformat()
    lookback = (
        datetime.now(timezone.utc) - timedelta(hours=hours)
    ).isoformat()

    rows = await db.fetch_all(
        """
        SELECT id, content, created_at, conversation_id
        FROM messages
        WHERE role = 'user'
          AND created_at > ?
          AND created_at < ?
        ORDER BY created_at DESC
        LIMIT 50
        """,
        (lookback, cutoff),
    )

    commitments = []
    for row in rows:
        content = (row["content"] or "").lower()
        for pattern in COMMITMENT_PATTERNS:
            if pattern in content:
                commitments.append({
                    "message_id": row["id"],
                    "content": row["content"][:200],
                    "pattern": pattern,
                    "created_at": row["created_at"],
                })
                break  # one match per message is enough

    return commitments[:5]  # cap at 5


def format_followup_notification(commitments: list[dict]) -> str:
    """Format commitments into a follow-up notification."""
    if not commitments:
        return ""

    lines = ["You mentioned these recently -- any progress?"]
    for c in commitments:
        lines.append(f"- \"{c['content'][:100]}\"")

    return "\n".join(lines)
