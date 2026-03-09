from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from odigos.db import Database
from odigos.memory.vectors import VectorMemory

try:
    from docling.chunking import HybridChunker
except ImportError:
    HybridChunker = None  # type: ignore[assignment,misc]

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _split_paragraphs(text: str) -> list[str]:
    """Simple fallback chunker: split on double newlines, skip empties."""
    chunks = [p.strip() for p in text.split("\n\n") if p.strip()]
    return chunks if chunks else [text] if text.strip() else []


class DocumentIngester:
    """Chunks and embeds documents into VectorMemory for RAG retrieval."""

    def __init__(self, db: Database, vector_memory: VectorMemory) -> None:
        self.db = db
        self.vector_memory = vector_memory

    async def ingest(
        self,
        text: str,
        filename: str,
        source_url: str | None = None,
        dl_doc=None,
    ) -> str:
        doc_id = str(uuid.uuid4())

        if dl_doc is not None and HybridChunker is not None:
            chunker = HybridChunker()
            chunks = [c.text for c in chunker.chunk(dl_doc) if c.text.strip()]
        else:
            chunks = _split_paragraphs(text)

        for chunk_text in chunks:
            await self.vector_memory.store(
                text=chunk_text,
                source_type="document_chunk",
                source_id=doc_id,
            )

        await self.db.execute(
            "INSERT INTO documents (id, filename, source_url, chunk_count) "
            "VALUES (?, ?, ?, ?)",
            (doc_id, filename, source_url, len(chunks)),
        )

        logger.info(
            "Ingested document '%s' (%d chunks) as %s",
            filename, len(chunks), doc_id,
        )
        return doc_id

    async def delete(self, document_id: str) -> None:
        rows = await self.db.fetch_all(
            "SELECT id FROM memory_vectors WHERE source_type = 'document_chunk' AND source_id = ?",
            (document_id,),
        )

        for row in rows:
            await self.db.execute(
                "DELETE FROM memory_vectors WHERE id = ?",
                (row["id"],),
            )

        await self.db.execute(
            "DELETE FROM documents WHERE id = ?",
            (document_id,),
        )

        logger.info("Deleted document %s (%d chunks)", document_id, len(rows))
