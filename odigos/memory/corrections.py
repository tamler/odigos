from __future__ import annotations

import uuid

from odigos.db import Database


class CorrectionsManager:
    """Stores and retrieves user corrections for learning from feedback."""

    def __init__(self, db: Database, vector_memory=None, memory_store=None) -> None:
        self.db = db
        # vector_memory kept for backward compat but unused (references dropped table)
        self._memory_store = memory_store

    async def store(
        self,
        conversation_id: str,
        original_response: str,
        correction: str,
        context: str,
        category: str,
    ) -> str:
        """Store a correction in the DB and embed it via MemoryStore.

        Returns the correction ID.
        """
        correction_id = str(uuid.uuid4())

        await self.db.execute(
            "INSERT INTO corrections (id, conversation_id, original_response, correction, context, category) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (correction_id, conversation_id, original_response, correction, context, category),
        )

        if self._memory_store:
            from odigos.memory.classifier import ClassificationResult
            classification = ClassificationResult(
                memory_type="correction",
                keywords=[category],
                tags=["user-feedback"],
                context_description=f"[{category}] {correction} (context: {context})",
            )
            await self._memory_store.store(
                content=f"{context}: {correction}",
                source_type="correction",
                source_id=correction_id,
                conversation_id=conversation_id,
                classification=classification,
            )

        return correction_id

    async def relevant(self, query: str, limit: int = 5) -> str:
        """Find corrections relevant to the query.

        Returns a formatted string with learned corrections, or "" if none found.
        """
        if not self.db:
            return ""

        rows = await self.db.fetch_all(
            "SELECT m.source_id FROM memories m WHERE m.memory_type = 'correction' "
            "AND m.status = 'active' ORDER BY m.created_at DESC LIMIT ?",
            (limit,),
        )
        if not rows:
            return ""

        lines = []
        for row in rows:
            corr = await self.db.fetch_one(
                "SELECT correction, context, category FROM corrections WHERE id = ?",
                (row["source_id"],),
            )
            if corr:
                lines.append(
                    f"- [{corr['category']}] {corr['correction']} (context: {corr['context']})"
                )

        if not lines:
            return ""

        header = "## Learned corrections\nApply these lessons from past feedback:"
        return header + "\n" + "\n".join(lines)
