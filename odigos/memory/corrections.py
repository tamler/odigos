from __future__ import annotations

import uuid

from odigos.db import Database
from odigos.memory.vectors import VectorMemory


class CorrectionsManager:
    """Stores and retrieves user corrections for learning from feedback."""

    def __init__(self, db: Database, vector_memory: VectorMemory) -> None:
        self.db = db
        self.vector_memory = vector_memory

    async def store(
        self,
        conversation_id: str,
        original_response: str,
        correction: str,
        context: str,
        category: str,
    ) -> str:
        """Store a correction in the DB and embed it for vector search.

        Returns the correction ID.
        """
        correction_id = str(uuid.uuid4())

        await self.db.execute(
            "INSERT INTO corrections (id, conversation_id, original_response, correction, context, category) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (correction_id, conversation_id, original_response, correction, context, category),
        )

        embedding_text = f"{context}: {correction}"
        await self.vector_memory.store(embedding_text, "correction", correction_id)

        return correction_id

    async def relevant(self, query: str, limit: int = 5) -> str:
        """Find corrections relevant to the query via vector search.

        Returns a formatted string with learned corrections, or "" if none found.
        """
        results = await self.vector_memory.search(query, limit=limit)

        # Filter to correction source_type only
        correction_results = [r for r in results if r.source_type == "correction"]

        if not correction_results:
            return ""

        # Fetch full rows from DB
        lines = []
        for result in correction_results:
            row = await self.db.fetch_one(
                "SELECT correction, context, category FROM corrections WHERE id = ?",
                (result.source_id,),
            )
            if row:
                lines.append(
                    f"- [{row['category']}] {row['correction']} (context: {row['context']})"
                )

        if not lines:
            return ""

        header = "## Learned corrections\nApply these lessons from past feedback:"
        return header + "\n" + "\n".join(lines)
