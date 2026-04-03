"""Notebook management tool — create, append, read, list notebooks."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from odigos.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from odigos.db import Database

logger = logging.getLogger(__name__)

BACKUP_DIR = Path("data/notebooks")


class ManageNotebookTool(BaseTool):
    name = "manage_notebook"
    category = "productivity"
    description = (
        "Create and write to notebooks. Use for notes, recipes, lyrics, "
        "meeting summaries, research, or any content the user might want to "
        "review and edit. Actions: create (new notebook), append (add entry), "
        "read (get entries), list (all notebooks)."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "append", "read", "list"],
                "description": "Action to perform",
            },
            "notebook_id": {
                "type": "string",
                "description": "Notebook ID (required for append/read)",
            },
            "title": {
                "type": "string",
                "description": "Notebook title (required for create)",
            },
            "content": {
                "type": "string",
                "description": "Entry content (for create with initial entry, and append)",
            },
            "mode": {
                "type": "string",
                "enum": ["general", "journal", "research", "creative", "meetings"],
                "description": "Notebook mode (default: general)",
            },
            "limit": {
                "type": "integer",
                "description": "Max entries to return for read (default: 20)",
            },
        },
        "required": ["action"],
    }

    def __init__(self, db: Database) -> None:
        self._db = db

    async def execute(self, params: dict) -> ToolResult:
        action = params.get("action", "")
        if action == "create":
            return await self._create(params)
        elif action == "append":
            return await self._append(params)
        elif action == "read":
            return await self._read(params)
        elif action == "list":
            return await self._list()
        return ToolResult(success=False, data="", error=f"Unknown action: {action}")

    async def _create(self, params: dict) -> ToolResult:
        title = (params.get("title") or "").strip()
        if not title:
            return ToolResult(success=False, data="", error="Title is required for create")

        content = (params.get("content") or "").strip()
        mode = params.get("mode", "general")
        now = datetime.now(timezone.utc).isoformat()
        nb_id = uuid.uuid4().hex

        await self._db.execute(
            "INSERT INTO notebooks (id, title, mode, collaboration, share_with_agent, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (nb_id, title, mode, "active", 1, now, now),
        )

        if content:
            entry_id = uuid.uuid4().hex
            await self._db.execute(
                "INSERT INTO notebook_entries (id, notebook_id, content, entry_type, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (entry_id, nb_id, content, "agent", "active", now, now),
            )
            await self._backup(nb_id)

        logger.info("Created notebook %s: %s", nb_id[:8], title)
        return ToolResult(
            success=True,
            data=f"Created notebook \"{title}\" (path: /notebooks/{nb_id})",
            side_effect={"notebook_id": nb_id, "path": f"/notebooks/{nb_id}"},
        )

    async def _append(self, params: dict) -> ToolResult:
        nb_id = (params.get("notebook_id") or "").strip()
        content = (params.get("content") or "").strip()

        if not nb_id:
            return ToolResult(success=False, data="", error="notebook_id is required for append")
        if not content:
            return ToolResult(success=False, data="", error="content is required for append")

        nb = await self._db.fetch_one("SELECT id, title, collaboration FROM notebooks WHERE id = ?", (nb_id,))
        if not nb:
            return ToolResult(success=False, data="", error=f"Notebook not found: {nb_id}")

        collab = nb["collaboration"]
        title = nb["title"]
        if collab == "read":
            return ToolResult(
                success=False, data="",
                error=f"Notebook \"{title}\" is read-only. Ask the user to change collaboration to 'active' or 'suggest'.",
            )

        now = datetime.now(timezone.utc).isoformat()
        entry_id = uuid.uuid4().hex
        await self._db.execute(
            "INSERT INTO notebook_entries (id, notebook_id, content, entry_type, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (entry_id, nb_id, content, "agent", "active", now, now),
        )
        await self._db.execute(
            "UPDATE notebooks SET updated_at = ? WHERE id = ?", (now, nb_id),
        )
        await self._backup(nb_id)

        logger.info("Appended entry to notebook %s", nb_id[:8])
        return ToolResult(
            success=True,
            data=f"Added entry to \"{title}\" (path: /notebooks/{nb_id})",
            side_effect={"notebook_id": nb_id, "entry_id": entry_id},
        )

    async def _read(self, params: dict) -> ToolResult:
        nb_id = (params.get("notebook_id") or "").strip()
        if not nb_id:
            return ToolResult(success=False, data="", error="notebook_id is required for read")

        nb = await self._db.fetch_one("SELECT id, title, mode FROM notebooks WHERE id = ?", (nb_id,))
        if not nb:
            return ToolResult(success=False, data="", error=f"Notebook not found: {nb_id}")

        title = nb["title"]
        mode = nb["mode"]
        limit = min(params.get("limit", 20), 50)

        entries = await self._db.fetch_all(
            "SELECT content, entry_type, created_at FROM notebook_entries "
            "WHERE notebook_id = ? AND status != 'rejected' "
            "ORDER BY created_at ASC LIMIT ?",
            (nb_id, limit),
        )

        if not entries:
            return ToolResult(
                success=True,
                data=f"Notebook \"{title}\" ({mode}) — no entries yet.",
            )

        lines = [f"Notebook: \"{title}\" (mode: {mode})\n"]
        for entry in entries:
            content = entry["content"]
            entry_type = entry["entry_type"]
            created = entry["created_at"]
            # Truncate long entries to avoid bloating agent context
            if len(content) > 2000:
                content = content[:2000] + "... (truncated)"
            lines.append(f"[{entry_type}] ({created[:10]})")
            lines.append(content)
            lines.append("")

        return ToolResult(success=True, data="\n".join(lines))

    async def _list(self) -> ToolResult:
        notebooks = await self._db.fetch_all(
            "SELECT id, title, mode, updated_at FROM notebooks ORDER BY updated_at DESC LIMIT 20",
        )

        if not notebooks:
            return ToolResult(success=True, data="No notebooks yet.")

        lines = []
        for nb in notebooks:
            nb_id = nb["id"]
            title = nb["title"]
            mode = nb["mode"]
            updated = nb["updated_at"]
            lines.append(
                f"- \"{title}\" ({mode}, updated: {updated[:10]}, "
                f"id: {nb_id}, path: /notebooks/{nb_id})"
            )

        return ToolResult(success=True, data="\n".join(lines))

    async def _backup(self, notebook_id: str) -> None:
        """Export notebook + entries to markdown file."""
        try:
            nb = await self._db.fetch_one("SELECT * FROM notebooks WHERE id = ?", (notebook_id,))
            if not nb:
                return

            title = nb["title"]
            mode = nb["mode"]
            collab = nb["collaboration"]
            share = nb["share_with_agent"]

            entries = await self._db.fetch_all(
                "SELECT * FROM notebook_entries WHERE notebook_id = ? AND status != 'rejected' "
                "ORDER BY created_at ASC",
                (notebook_id,),
            )

            share_label = "yes" if share else "no"
            lines = [
                f"# {title}",
                f"Mode: {mode} | Collaboration: {collab} | Share: {share_label}",
                "",
            ]

            for entry in entries:
                content = entry["content"]
                created = entry["created_at"]
                mood = entry.get("mood") or ""
                lines.append("---")
                lines.append("")
                lines.append(f"## {created}")
                if mood:
                    lines.append(f"Mood: {mood}")
                lines.append("")
                lines.append(content)
                lines.append("")

            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            (BACKUP_DIR / f"{notebook_id}.md").write_text("\n".join(lines), encoding="utf-8")
        except Exception as exc:
            logger.warning("Notebook backup failed for %s: %s", notebook_id[:8], exc)
