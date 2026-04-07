"""Write-on-change disk backup for conversations, kanban boards, and user data.

All user-visible data should exist as files, not just in the database.
The DB is for fast agent access. The files are for user backup and recovery.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from odigos.db import Database

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")


async def export_conversation(db: Database, conversation_id: str) -> None:
    """Export a conversation to data/conversations/{id}.md"""
    try:
        conv = await db.fetch_one(
            "SELECT id, channel, title, created_at FROM conversations WHERE id = ?",
            (conversation_id,),
        )
        if not conv:
            return

        messages = await db.fetch_all(
            "SELECT role, content, created_at FROM messages "
            "WHERE conversation_id = ? ORDER BY created_at ASC",
            (conversation_id,),
        )
        if not messages:
            return

        title = conv["title"] or "Untitled"
        safe_id = conversation_id.replace(":", "_").replace("/", "_")

        lines = [
            f"# {title}",
            f"Channel: {conv['channel']} | Started: {conv['created_at']}",
            "",
        ]

        for msg in messages:
            role = msg["role"].capitalize()
            timestamp = msg["created_at"] or ""
            lines.append(f"## {role} ({timestamp})")
            lines.append("")
            lines.append(msg["content"])
            lines.append("")

        out_dir = DATA_DIR / "conversations"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{safe_id}.md").write_text("\n".join(lines), encoding="utf-8")
    except Exception:
        logger.debug("Could not export conversation %s", conversation_id, exc_info=True)


async def export_kanban_board(db: Database, board_id: str) -> None:
    """Export a kanban board to data/kanban/{id}.md"""
    try:
        board = await db.fetch_one(
            "SELECT id, title, description FROM kanban_boards WHERE id = ?",
            (board_id,),
        )
        if not board:
            return

        columns = await db.fetch_all(
            "SELECT id, title, position FROM kanban_columns "
            "WHERE board_id = ? ORDER BY position ASC",
            (board_id,),
        )
        cards = await db.fetch_all(
            "SELECT title, description, column_id, position, priority "
            "FROM kanban_cards WHERE board_id = ? ORDER BY position ASC",
            (board_id,),
        )

        cards_by_col = {}
        for card in cards:
            cards_by_col.setdefault(card["column_id"], []).append(card)

        lines = [
            f"# {board['title']}",
        ]
        if board.get("description"):
            lines.append(f"{board['description']}")
        lines.append("")

        for col in columns:
            col_cards = cards_by_col.get(col["id"], [])
            lines.append(f"## {col['title']} ({len(col_cards)})")
            lines.append("")
            for card in col_cards:
                priority = f" [{card['priority']}]" if card.get("priority") and card["priority"] != "medium" else ""
                lines.append(f"- {card['title']}{priority}")
                if card.get("description"):
                    lines.append(f"  {card['description'][:200]}")
            lines.append("")

        out_dir = DATA_DIR / "kanban"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{board_id}.md").write_text("\n".join(lines), encoding="utf-8")
    except Exception:
        logger.debug("Could not export kanban board %s", board_id, exc_info=True)


async def export_user_data(db: Database) -> None:
    """Export user facts and profile to data/user/"""
    try:
        out_dir = DATA_DIR / "user"
        out_dir.mkdir(parents=True, exist_ok=True)

        # Facts
        facts = await db.fetch_all(
            "SELECT category, fact, created_at FROM user_facts ORDER BY category, created_at"
        )
        if facts:
            lines = ["# User Facts", ""]
            current_cat = None
            for row in facts:
                if row["category"] != current_cat:
                    current_cat = row["category"]
                    lines.append(f"## {current_cat}")
                    lines.append("")
                lines.append(f"- {row['fact']} ({row['created_at']})")
            (out_dir / "facts.md").write_text("\n".join(lines), encoding="utf-8")

        # Profile
        profile = await db.fetch_one(
            "SELECT summary, communication_style, preferences, expertise_areas, last_analyzed_at "
            "FROM user_profile WHERE id = 'owner'"
        )
        if profile and profile.get("summary"):
            lines = [
                "# User Profile",
                f"Last analyzed: {profile.get('last_analyzed_at', 'never')}",
                "",
                "## Summary",
                profile["summary"] or "",
                "",
            ]
            if profile.get("communication_style"):
                lines.extend(["## Communication Style", profile["communication_style"], ""])
            if profile.get("preferences"):
                lines.extend(["## Preferences", profile["preferences"], ""])
            if profile.get("expertise_areas"):
                lines.extend(["## Expertise", profile["expertise_areas"], ""])
            (out_dir / "profile.md").write_text("\n".join(lines), encoding="utf-8")
    except Exception:
        logger.debug("Could not export user data", exc_info=True)
