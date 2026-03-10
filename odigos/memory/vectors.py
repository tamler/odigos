from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

import chromadb

if TYPE_CHECKING:
    from odigos.providers.embeddings import EmbeddingProvider

logger = logging.getLogger(__name__)

COLLECTION_NAME = "memory_vectors"


@dataclass
class MemoryResult:
    content_preview: str
    source_type: str
    source_id: str
    distance: float
    when_to_use: str = ""
    memory_type: str = "general"


class VectorMemory:
    """ChromaDB-backed vector store for semantic memory search."""

    def __init__(self, embedder: EmbeddingProvider, persist_dir: str = "data/chroma") -> None:
        self.embedder = embedder
        self._persist_dir = persist_dir
        self._client: chromadb.ClientAPI | None = None
        self._collection: chromadb.Collection | None = None

    async def initialize(self) -> None:
        """Create or open the ChromaDB persistent client and collection."""
        loop = asyncio.get_running_loop()
        self._client = await loop.run_in_executor(
            None,
            partial(chromadb.PersistentClient, path=self._persist_dir),
        )
        self._collection = await loop.run_in_executor(
            None,
            partial(
                self._client.get_or_create_collection,
                name=COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            ),
        )

    async def store(self, text: str, source_type: str, source_id: str, when_to_use: str = "", memory_type: str = "general") -> str:
        """Embed text and store in ChromaDB. Returns the vector ID."""
        embed_input = when_to_use if when_to_use else text
        vector = await self.embedder.embed(embed_input)
        vec_id = str(uuid.uuid4())

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            partial(
                self._collection.add,
                ids=[vec_id],
                embeddings=[vector],
                metadatas=[{
                    "source_type": source_type,
                    "source_id": source_id,
                    "content_preview": text[:500],
                    "when_to_use": when_to_use,
                    "memory_type": memory_type,
                }],
                documents=[text[:500]],
            ),
        )
        return vec_id

    async def search(
        self, query: str, limit: int = 5, source_type: str | None = None,
        memory_type: str | None = None,
    ) -> list[MemoryResult]:
        """Embed query and find nearest neighbors."""
        loop = asyncio.get_running_loop()
        count = await loop.run_in_executor(None, self._collection.count)
        if count == 0:
            return []

        vector = await self.embedder.embed_query(query)

        conditions = []
        if source_type:
            conditions.append({"source_type": source_type})
        if memory_type:
            conditions.append({"memory_type": memory_type})
        if len(conditions) == 1:
            where_filter = conditions[0]
        elif len(conditions) > 1:
            where_filter = {"$and": conditions}
        else:
            where_filter = None

        results = await loop.run_in_executor(
            None,
            partial(
                self._collection.query,
                query_embeddings=[vector],
                n_results=min(limit, count),
                where=where_filter,
            ),
        )

        memory_results = []
        if results and results["ids"] and results["ids"][0]:
            for i, _id in enumerate(results["ids"][0]):
                meta = results["metadatas"][0][i]
                dist = results["distances"][0][i] if results.get("distances") else 0.0
                memory_results.append(
                    MemoryResult(
                        content_preview=meta.get("content_preview", ""),
                        source_type=meta.get("source_type", ""),
                        source_id=meta.get("source_id", ""),
                        distance=dist,
                        when_to_use=meta.get("when_to_use", ""),
                        memory_type=meta.get("memory_type", "general"),
                    )
                )

        return memory_results

    async def count(self) -> int:
        """Return total number of vectors stored."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._collection.count)
