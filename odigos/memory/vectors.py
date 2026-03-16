from __future__ import annotations

import logging
import struct
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.db import Database
    from odigos.providers.embeddings import EmbeddingProvider

logger = logging.getLogger(__name__)


@dataclass
class MemoryResult:
    content_preview: str
    source_type: str
    source_id: str
    distance: float
    when_to_use: str = ""
    memory_type: str = "general"


def _serialize_f32(vec: list[float]) -> bytes:
    """Serialize a list of floats to a compact binary format for sqlite-vec."""
    return struct.pack(f"{len(vec)}f", *vec)


class VectorMemory:
    """SQLite-backed vector store using sqlite-vec for semantic memory search."""

    def __init__(self, embedder: EmbeddingProvider, db: Database) -> None:
        self.embedder = embedder
        self.db = db

    async def initialize(self) -> None:
        """No-op — schema is handled by migrations."""
        pass

    async def store(
        self,
        text: str,
        source_type: str,
        source_id: str,
        when_to_use: str = "",
        memory_type: str = "general",
    ) -> str:
        """Embed text and store in SQLite. Returns the vector ID."""
        embed_input = when_to_use if when_to_use else text
        vector = await self.embedder.embed(embed_input)
        vec_id = str(uuid.uuid4())

        await self.db.execute_in_transaction([
            (
                "INSERT INTO memory_entries (id, content_preview, source_type, source_id, when_to_use, memory_type) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (vec_id, text[:500], source_type, source_id, when_to_use, memory_type),
            ),
            (
                "INSERT INTO memory_vec (id, embedding) VALUES (?, ?)",
                (vec_id, _serialize_f32(vector)),
            ),
        ])
        return vec_id

    async def search(
        self,
        query: str,
        limit: int = 5,
        source_type: str | None = None,
        memory_type: str | None = None,
    ) -> list[MemoryResult]:
        """Embed query and find nearest neighbors via sqlite-vec."""
        count = await self.count()
        if count == 0:
            return []

        vector = await self.embedder.embed_query(query)

        where_clauses = []
        params: list = []
        if source_type:
            where_clauses.append("e.source_type = ?")
            params.append(source_type)
        if memory_type:
            where_clauses.append("e.memory_type = ?")
            params.append(memory_type)

        where_sql = ""
        if where_clauses:
            where_sql = "AND " + " AND ".join(where_clauses)

        # sqlite-vec KNN: MATCH on embedding column, ORDER BY distance
        knn_sql = f"""
            SELECT e.id, e.content_preview, e.source_type, e.source_id,
                   e.when_to_use, e.memory_type, v.distance
            FROM (
                SELECT id, distance
                FROM memory_vec
                WHERE embedding MATCH ?
                ORDER BY distance
                LIMIT ?
            ) v
            JOIN memory_entries e ON e.id = v.id
            {where_sql}
        """
        # Over-fetch from vec to account for filtering
        fetch_limit = min(limit * 3, count) if where_clauses else min(limit, count)
        all_params = [_serialize_f32(vector), fetch_limit] + params

        rows = await self.db.fetch_all(knn_sql, tuple(all_params))

        results = []
        for row in rows[:limit]:
            results.append(
                MemoryResult(
                    content_preview=row["content_preview"],
                    source_type=row["source_type"],
                    source_id=row["source_id"],
                    distance=row["distance"],
                    when_to_use=row.get("when_to_use", ""),
                    memory_type=row.get("memory_type", "general"),
                )
            )
        return results

    async def search_fts(
        self, query: str, limit: int = 20, source_type: str | None = None,
    ) -> list[MemoryResult]:
        """Full-text keyword search via FTS5."""
        _FTS5_RESERVED = {"AND", "OR", "NOT", "NEAR"}
        clean_terms = []
        for word in query.split():
            cleaned = "".join(c for c in word if c.isalnum())
            if cleaned and cleaned.upper() not in _FTS5_RESERVED:
                clean_terms.append(cleaned)

        if not clean_terms:
            return []

        fts_query = " OR ".join(clean_terms)

        if source_type:
            rows = await self.db.fetch_all(
                """
                SELECT e.id, e.content_preview, e.source_type, e.source_id,
                       e.when_to_use, e.memory_type,
                       rank AS distance
                FROM memory_fts
                JOIN memory_entries e ON e.rowid = memory_fts.rowid
                WHERE memory_fts MATCH ? AND e.source_type = ?
                ORDER BY rank
                LIMIT ?
                """,
                (fts_query, source_type, limit),
            )
        else:
            rows = await self.db.fetch_all(
                """
                SELECT e.id, e.content_preview, e.source_type, e.source_id,
                       e.when_to_use, e.memory_type,
                       rank AS distance
                FROM memory_fts
                JOIN memory_entries e ON e.rowid = memory_fts.rowid
                WHERE memory_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (fts_query, limit),
            )

        return [
            MemoryResult(
                content_preview=row["content_preview"],
                source_type=row["source_type"],
                source_id=row["source_id"],
                distance=row["distance"],
                when_to_use=row.get("when_to_use", ""),
                memory_type=row.get("memory_type", "general"),
            )
            for row in rows
        ]

    async def count(self) -> int:
        """Return total number of vectors stored."""
        row = await self.db.fetch_one("SELECT COUNT(*) as cnt FROM memory_entries")
        return row["cnt"] if row else 0

    async def delete_by_source(self, source_type: str, source_id: str) -> None:
        """Delete all entries matching source_type and source_id."""
        rows = await self.db.fetch_all(
            "SELECT id FROM memory_entries WHERE source_type = ? AND source_id = ?",
            (source_type, source_id),
        )
        if not rows:
            return

        ids = [row["id"] for row in rows]
        placeholders = ",".join("?" * len(ids))

        await self.db.execute_in_transaction([
            (f"DELETE FROM memory_vec WHERE id IN ({placeholders})", tuple(ids)),
            (
                "DELETE FROM memory_entries WHERE source_type = ? AND source_id = ?",
                (source_type, source_id),
            ),
        ])
