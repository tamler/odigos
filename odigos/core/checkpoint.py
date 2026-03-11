"""CheckpointManager: deadman switch for agent evolution.

Known-good state lives on disk. Trial overrides live in DB only.
If the process crashes, disk state is all that remains.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from odigos.personality.section_registry import SectionRegistry

if TYPE_CHECKING:
    from odigos.db import Database

logger = logging.getLogger(__name__)


class CheckpointManager:

    def __init__(
        self,
        db: Database,
        sections_dir: str,
        personality_path: str = "data/personality.yaml",
        skills_dir: str = "skills",
    ) -> None:
        self.db = db
        self._sections_dir = sections_dir
        self._personality_path = personality_path
        self._skills_dir = skills_dir
        self._section_registry = SectionRegistry(sections_dir)

    async def create_checkpoint(self, label: str = "", parent_id: str | None = None) -> str:
        """Snapshot current disk state into a checkpoint record."""
        cp_id = str(uuid.uuid4())

        personality_snapshot = ""
        if self._personality_path:
            p_path = Path(self._personality_path)
            if p_path.is_file():
                personality_snapshot = p_path.read_text()

        sections_snapshot = {}
        s_dir = Path(self._sections_dir)
        if s_dir.exists():
            for f in s_dir.glob("*.md"):
                sections_snapshot[f.stem] = f.read_text()

        skills_snapshot = {}
        sk_dir = Path(self._skills_dir)
        if sk_dir.exists():
            for f in sk_dir.glob("*.md"):
                skills_snapshot[f.stem] = f.read_text()

        await self.db.execute(
            "INSERT INTO checkpoints (id, parent_id, label, personality_snapshot, "
            "prompt_sections_snapshot, skills_snapshot) VALUES (?, ?, ?, ?, ?, ?)",
            (
                cp_id,
                parent_id,
                label,
                personality_snapshot,
                json.dumps(sections_snapshot),
                json.dumps(skills_snapshot),
            ),
        )
        return cp_id

    async def get_working_sections(self) -> list:
        """Load sections from disk, merging any active non-expired trial overrides."""
        overrides = await self._get_active_overrides()
        return self._section_registry.load_all(overrides=overrides)

    async def _get_active_overrides(self) -> dict[str, str]:
        """Get overrides from active, non-expired trials."""
        now = datetime.now(timezone.utc).isoformat()
        rows = await self.db.fetch_all(
            "SELECT o.target_name, o.override_content "
            "FROM trial_overrides o "
            "JOIN trials t ON o.trial_id = t.id "
            "WHERE t.status = 'active' AND t.expires_at > ?",
            (now,),
        )
        return {row["target_name"]: row["override_content"] for row in rows}

    async def promote_trial(self, trial_id: str) -> str:
        """Write trial overrides to disk, creating a new checkpoint."""
        overrides = await self.db.fetch_all(
            "SELECT target_type, target_name, override_content "
            "FROM trial_overrides WHERE trial_id = ?",
            (trial_id,),
        )

        cp_id = await self.create_checkpoint(label=f"pre-promote-{trial_id[:8]}")

        for row in overrides:
            if row["target_type"] == "prompt_section":
                path = Path(self._sections_dir) / f"{row['target_name']}.md"
                existing = ""
                if path.exists():
                    existing = path.read_text()
                frontmatter = _extract_frontmatter(existing)
                path.write_text(f"{frontmatter}{row['override_content']}")

        await self.db.execute(
            "DELETE FROM trial_overrides WHERE trial_id = ?", (trial_id,)
        )
        await self.db.execute(
            "UPDATE trials SET status = 'promoted', result_notes = 'Promoted to known-good' "
            "WHERE id = ?",
            (trial_id,),
        )
        logger.info("Promoted trial %s, new checkpoint %s", trial_id[:8], cp_id[:8])
        return cp_id

    async def revert_trial(self, trial_id: str, reason: str = "") -> None:
        """Delete trial overrides (disk unchanged = automatic revert)."""
        await self.db.execute(
            "DELETE FROM trial_overrides WHERE trial_id = ?", (trial_id,)
        )
        await self.db.execute(
            "UPDATE trials SET status = 'reverted', result_notes = ? WHERE id = ?",
            (reason, trial_id),
        )
        logger.info("Reverted trial %s: %s", trial_id[:8], reason)

    async def get_active_trial(self) -> dict | None:
        """Get the currently active trial, if any."""
        now = datetime.now(timezone.utc).isoformat()
        return await self.db.fetch_one(
            "SELECT * FROM trials WHERE status = 'active' AND expires_at > ? "
            "ORDER BY started_at DESC LIMIT 1",
            (now,),
        )

    async def expire_stale_trials(self) -> int:
        """Expire any trials past their time cap. Returns count expired."""
        now = datetime.now(timezone.utc).isoformat()
        stale = await self.db.fetch_all(
            "SELECT id FROM trials WHERE status = 'active' AND expires_at <= ?",
            (now,),
        )
        for row in stale:
            await self.revert_trial(row["id"], reason="expired")
        return len(stale)


def _extract_frontmatter(text: str) -> str:
    """Extract YAML frontmatter block (including delimiters) from text."""
    if not text.startswith("---"):
        return "---\npriority: 50\nalways_include: true\n---\n"
    parts = text.split("---", 2)
    if len(parts) < 3:
        return "---\npriority: 50\nalways_include: true\n---\n"
    return f"---{parts[1]}---\n"
