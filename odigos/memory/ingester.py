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

        # Use HybridChunker on the full DoclingDocument for better structural
        # chunks. This intentionally bypasses DoclingProvider's max_content_chars
        # truncation -- RAG benefits from indexing the complete document.
        if dl_doc is not None and HybridChunker is not None:
            chunker = HybridChunker()
            chunks = [c.text for c in chunker.chunk(dl_doc) if c.text.strip()]
        else:
            chunks = _split_paragraphs(text)

        # Insert document record first so partial failures are recoverable
        await self.db.execute(
            "INSERT INTO documents (id, filename, source_url, chunk_count) "
            "VALUES (?, ?, ?, ?)",
            (doc_id, filename, source_url, 0),
        )

        stored_count = 0
        for chunk_text in chunks:
            try:
                await self.vector_memory.store(
                    text=chunk_text,
                    source_type="document_chunk",
                    source_id=doc_id,
                )
                stored_count += 1
            except Exception:
                logger.warning(
                    "Failed to store chunk %d/%d for document %s",
                    stored_count + 1, len(chunks), doc_id, exc_info=True,
                )
                break

        # Update with actual stored chunk count
        await self.db.execute(
            "UPDATE documents SET chunk_count = ? WHERE id = ?",
            (stored_count, doc_id),
        )

        logger.info(
            "Ingested document '%s' (%d/%d chunks) as %s",
            filename, stored_count, len(chunks), doc_id,
        )
        return doc_id

    async def delete(self, document_id: str) -> None:
        """Delete a document and all its chunks from vector memory."""
        # Count for logging before deletion
        row = await self.db.fetch_one(
            "SELECT chunk_count FROM documents WHERE id = ?",
            (document_id,),
        )
        chunk_count = row["chunk_count"] if row else 0

        # Single query to delete all chunks
        await self.db.execute(
            "DELETE FROM memory_vectors WHERE source_type = 'document_chunk' AND source_id = ?",
            (document_id,),
        )

        await self.db.execute(
            "DELETE FROM documents WHERE id = ?",
            (document_id,),
        )

        logger.info("Deleted document %s (%d chunks)", document_id, chunk_count)
