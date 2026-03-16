"""Documents list and management API."""

import logging
import os

from fastapi import APIRouter, Depends, HTTPException

from odigos.api.deps import get_db, get_doc_ingester, require_auth
from odigos.db import Database
from odigos.memory.ingester import DocumentIngester

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/documents",
    dependencies=[Depends(require_auth)],
)

SOFT_CHUNK_LIMIT = 200_000


@router.get("")
async def list_documents(
    db: Database = Depends(get_db),
):
    """List all documents with metadata and storage summary."""
    rows = await db.fetch_all(
        "SELECT id, filename, file_size, chunk_count, status, ingested_at "
        "FROM documents ORDER BY ingested_at DESC"
    )
    documents = [dict(r) for r in rows]

    total_documents = len(documents)
    total_chunks = sum(d.get("chunk_count", 0) or 0 for d in documents)
    total_size_bytes = sum(d.get("file_size", 0) or 0 for d in documents)
    estimated_size_mb = round(total_size_bytes / (1024 * 1024), 2)

    return {
        "documents": documents,
        "summary": {
            "total_documents": total_documents,
            "total_chunks": total_chunks,
            "estimated_size_mb": estimated_size_mb,
        },
        "storage_warning": total_chunks > SOFT_CHUNK_LIMIT,
    }


@router.delete("/{document_id}")
async def delete_document(
    document_id: str,
    db: Database = Depends(get_db),
    ingester: DocumentIngester = Depends(get_doc_ingester),
):
    """Delete a document and all its vector chunks."""
    row = await db.fetch_one(
        "SELECT filename FROM documents WHERE id = ?",
        (document_id,),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")

    filename = row["filename"]
    await ingester.delete(document_id)

    return {"ok": True, "message": f"Deleted document '{filename}'"}


@router.get("/storage")
async def storage_stats(
    db: Database = Depends(get_db),
):
    """Return storage statistics."""
    doc_row = await db.fetch_one(
        "SELECT COUNT(*) as total_documents, "
        "COALESCE(SUM(chunk_count), 0) as total_chunks, "
        "COALESCE(SUM(file_size), 0) as total_size_bytes "
        "FROM documents"
    )
    total_documents = doc_row["total_documents"] if doc_row else 0
    total_chunks = doc_row["total_chunks"] if doc_row else 0
    total_size_bytes = doc_row["total_size_bytes"] if doc_row else 0

    # Get actual DB file size
    db_file_size = 0
    try:
        db_file_size = os.path.getsize(db.path)
    except (OSError, AttributeError):
        pass

    return {
        "total_documents": total_documents,
        "total_chunks": total_chunks,
        "estimated_size_mb": round(total_size_bytes / (1024 * 1024), 2),
        "db_file_size_mb": round(db_file_size / (1024 * 1024), 2),
        "near_limit": total_chunks > SOFT_CHUNK_LIMIT,
    }
