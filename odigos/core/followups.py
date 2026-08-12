"""Follow-up detection: find user commitments and create reminders."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from odigos.core.capabilities import TextBlob

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

COMMITMENT_VERBS = {
    "will", "going", "need", "should", "must",
    "promise", "plan", "intend", "commit",
}


def _detect_commitment(content: str) -> str | None:
    """Detect commitment language using TextBlob NLP."""
    if TextBlob is not None:
        try:
            blob = TextBlob(content)
            words = [str(w).lower() for w in blob.words]
            for verb in COMMITMENT_VERBS:
                if verb in words:
                    for sentence in blob.sentences:
                        s_words = [
                            str(w).lower()
                            for w in sentence.words
                        ]
                        if verb in s_words:
                            return str(sentence)
        except Exception:
            pass
    # Fallback: check original patterns
    lower = content.lower()
    for pattern in COMMITMENT_PATTERNS:
        if pattern in lower:
            return content[:200]
    return None


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
        content = row["content"] or ""
        match = _detect_commitment(content)
        if match:
            commitments.append({
                "message_id": row["id"],
                "content": match[:200],
                "pattern": "nlp",
                "created_at": row["created_at"],
            })

    return commitments[:5]  # cap at 5


def format_followup_notification(commitments: list[dict]) -> str:
    """Format commitments into a follow-up notification."""
    if not commitments:
        return ""

    lines = ["You mentioned these recently -- any progress?"]
    for c in commitments:
        lines.append(f"- \"{c['content'][:100]}\"")

    return "\n".join(lines)
