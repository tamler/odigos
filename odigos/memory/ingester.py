from __future__ import annotations

import logging
import uuid
from odigos.db import Database
from odigos.memory.chunking import ChunkingService
from odigos.memory.vectors import VectorMemory

logger = logging.getLogger(__name__)


class DocumentIngester:
    """Chunks and embeds documents into VectorMemory for RAG retrieval."""

    def __init__(
        self, db: Database, vector_memory: VectorMemory,
        chunking_service: ChunkingService | None = None,
    ) -> None:
        self.db = db
        self.vector_memory = vector_memory
        self.chunking = chunking_service or ChunkingService()

    async def ingest(
        self,
        text: str,
        filename: str,
        source_url: str | None = None,
        file_path: str | None = None,
        file_size: int | None = None,
        content_hash: str | None = None,
        conversation_id: str | None = None,
        force: bool = False,
    ) -> str:
        # Check for existing document with same filename
        existing = await self.db.fetch_one(
            "SELECT id, content_hash FROM documents WHERE filename = ?",
            (filename,),
        )
        if existing is not None:
            if not force and content_hash and existing["content_hash"] == content_hash:
                logger.info(
                    "Document '%s' already ingested with same content hash, skipping",
                    filename,
                )
                return existing["id"]
            # Different content or forced re-ingest — delete old and re-process
            await self.delete(existing["id"])

        doc_id = str(uuid.uuid4())

        # Detect content type from filename
        content_type = "document"
        if filename.endswith((".py", ".js", ".ts", ".go", ".rs", ".java", ".c", ".cpp")):
            content_type = "code"

        chunks = self.chunking.chunk(text, content_type=content_type)

        # Insert document record with provenance, status='processing'
        await self.db.execute(
            "INSERT INTO documents "
            "(id, filename, source_url, chunk_count, file_path, file_size, "
            "content_hash, conversation_id, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (doc_id, filename, source_url, 0, file_path, file_size,
             content_hash, conversation_id, "processing"),
        )

        stored_count = 0
        for chunk_text in chunks:
            when_to_use = f"when referencing content from '{filename}': {chunk_text[:100]}"
            try:
                await self.vector_memory.store(
                    text=chunk_text,
                    source_type="document_chunk",
                    source_id=doc_id,
                    when_to_use=when_to_use,
                )
                stored_count += 1
            except Exception:
                logger.warning(
                    "Failed to store chunk %d/%d for document %s",
                    stored_count + 1, len(chunks), doc_id, exc_info=True,
                )
                break

        # Determine final status
        status = "ingested" if stored_count > 0 else "failed"

        # Update with actual stored chunk count and final status
        await self.db.execute(
            "UPDATE documents SET chunk_count = ?, status = ? WHERE id = ?",
            (stored_count, status, doc_id),
        )

        logger.info(
            "Ingested document '%s' (%d/%d chunks, status=%s) as %s",
            filename, stored_count, len(chunks), status, doc_id,
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

        await self.vector_memory.delete_by_source("document_chunk", document_id)

        await self.db.execute(
            "DELETE FROM documents WHERE id = ?",
            (document_id,),
        )

        logger.info("Deleted document %s (%d chunks)", document_id, chunk_count)

    async def get_document_metadata(self, document_id: str) -> dict | None:
        """Return full metadata for a document, or None if not found."""
        return await self.db.fetch_one(
            "SELECT id, filename, source_url, chunk_count, file_path, file_size, "
            "content_hash, conversation_id, status, ingested_at "
            "FROM documents WHERE id = ?",
            (document_id,),
        )
