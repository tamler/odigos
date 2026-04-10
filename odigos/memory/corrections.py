"""User correction storage and retrieval.

Corrections are AGENT SELF-IMPROVEMENT data, not user memory. They drive the
consolidation pipeline that produces operational_rules.md and
behavioral_principles.md personality sections. This module intentionally does
NOT write corrections to the memory layer — the separation keeps the
user-facing memory system clean and the self-improvement layer focused.

For unconsolidated corrections, `relevant()` surfaces the most recent ones as
a belt-and-suspenders fallback before they're baked into the prompt sections
by the consolidation job.
"""
from __future__ import annotations

import uuid

from odigos.db import Database


class CorrectionsManager:
    """Stores and retrieves user corrections for agent self-improvement."""

    def __init__(self, db: Database, vector_memory=None, memory_store=None) -> None:
        self.db = db
        # vector_memory and memory_store kept for backward-compat with bootstrap
        # wiring but intentionally unused — corrections live only in the
        # corrections table, not in the memory layer.

    async def store(
        self,
        conversation_id: str,
        original_response: str,
        correction: str,
        context: str,
        category: str,
    ) -> str:
        """Store a correction in the corrections table.

        Returns the correction ID. Does NOT write to the memory layer —
        corrections are self-improvement data, not user memories.
        """
        correction_id = str(uuid.uuid4())

        await self.db.execute(
            "INSERT INTO corrections "
            "(id, conversation_id, original_response, correction, context, category) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (correction_id, conversation_id, original_response, correction, context, category),
        )

        return correction_id

    async def relevant(self, query: str, limit: int = 5) -> str:
        """Return recent unconsolidated corrections as a formatted block.

        This is a belt-and-suspenders fallback for corrections not yet
        consolidated into operational_rules.md / behavioral_principles.md.
        Once consolidated, corrections are in the system prompt always and
        don't need to be surfaced here.

        Returns a formatted markdown block, or "" if no relevant corrections.
        """
        if not self.db:
            return ""

        rows = await self.db.fetch_all(
            "SELECT correction, context, category FROM corrections "
            "WHERE consolidated_at IS NULL "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        if not rows:
            return ""

        lines = [
            f"- [{row['category']}] {row['correction']} (context: {row['context']})"
            for row in rows
        ]

        header = "## Recent corrections (not yet consolidated)\nApply these lessons until they're baked into the prompt sections:"
        return header + "\n" + "\n".join(lines)
