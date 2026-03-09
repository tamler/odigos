from __future__ import annotations

import struct
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from odigos.db import Database

if TYPE_CHECKING:
    from odigos.providers.embeddings import EmbeddingProvider

VECTOR_DIMENSIONS = 768


@dataclass
class MemoryResult:
    content_preview: str
    source_type: str
    source_id: str
    distance: float


class VectorMemory:
    """sqlite-vec backed vector store for semantic memory search."""

    def __init__(self, db: Database, embedder: EmbeddingProvider) -> None:
        self.db = db
        self.embedder = embedder

    async def initialize(self) -> None:
        """Create the vec0 virtual table if it doesn't exist."""
        await self.db.conn.execute(
            f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_vectors USING vec0(
                id TEXT PRIMARY KEY,
                embedding FLOAT[{VECTOR_DIMENSIONS}],
                +source_type TEXT,
                +source_id TEXT,
                +content_preview TEXT,
                +created_at TEXT
            )
            """
        )
        await self.db.conn.commit()

    async def store(self, text: str, source_type: str, source_id: str) -> str:
        """Embed text and store in vector table. Returns the vector ID."""
        vector = await self.embedder.embed(text)
        vec_id = str(uuid.uuid4())

        await self.db.conn.execute(
            "INSERT INTO memory_vectors (id, embedding, source_type, source_id, "
            "content_preview, created_at) VALUES (?, ?, ?, ?, ?, datetime('now'))",
            (vec_id, _serialize_vector(vector), source_type, source_id, text[:500]),
        )
        await self.db.conn.commit()
        return vec_id

    async def search(self, query: str, limit: int = 5) -> list[MemoryResult]:
        """Embed query and find nearest neighbors."""
        vector = await self.embedder.embed_query(query)

        cursor = await self.db.conn.execute(
            """
            SELECT id, distance, source_type, source_id, content_preview
            FROM memory_vectors
            WHERE embedding MATCH ?
            ORDER BY distance
            LIMIT ?
            """,
            (_serialize_vector(vector), limit),
        )
        rows = await cursor.fetchall()

        return [
            MemoryResult(
                content_preview=row[4],
                source_type=row[2],
                source_id=row[3],
                distance=row[1],
            )
            for row in rows
        ]


def _serialize_vector(vector: list[float]) -> bytes:
    """Serialize a float vector to bytes for sqlite-vec."""
    return struct.pack(f"{len(vector)}f", *vector)
