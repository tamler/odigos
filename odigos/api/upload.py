"""File upload endpoint with auto-ingestion into agent memory."""

import asyncio
import hashlib
import logging
import os
import secrets

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from odigos.api.deps import get_doc_ingester, get_markitdown, get_upload_dir, require_api_key
from odigos.memory.ingester import DocumentIngester
from odigos.providers.markitdown import MarkItDownProvider

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB
PREVIEW_CHARS = 2000

router = APIRouter(
    prefix="/api",
    dependencies=[Depends(require_api_key)],
)


@router.post("/upload")
async def upload_file(
    file: UploadFile,
    upload_dir: str = Depends(get_upload_dir),
    ingester: DocumentIngester = Depends(get_doc_ingester),
    markitdown: MarkItDownProvider = Depends(get_markitdown),
):
    """Upload a file, auto-ingest into memory, return metadata + content preview."""
    os.makedirs(upload_dir, exist_ok=True)

    file_id = secrets.token_hex(8)
    safe_name = os.path.basename(file.filename or "upload")
    dest = os.path.join(upload_dir, f"{file_id}_{safe_name}")

    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (50 MB max)")

    with open(dest, "wb") as f:
        f.write(content)

    content_hash = hashlib.sha256(content).hexdigest()

    # Extract text via MarkItDown
    extracted_text = None
    chunk_count = 0
    status = "failed"
    doc_id = None

    try:
        extracted_text = await asyncio.to_thread(markitdown.convert_file, dest)
    except Exception:
        logger.warning("Text extraction failed for %s", safe_name, exc_info=True)

    if extracted_text:
        try:
            doc_id = await ingester.ingest(
                text=extracted_text,
                filename=safe_name,
                file_path=dest,
                file_size=len(content),
                content_hash=content_hash,
            )
            row = await ingester.get_document_metadata(doc_id)
            if row:
                chunk_count = row["chunk_count"]
                status = row["status"]
        except Exception:
            logger.warning("Ingestion failed for %s", safe_name, exc_info=True)
            status = "failed"

    return {
        "id": file_id,
        "document_id": doc_id,
        "filename": file.filename,
        "size": len(content),
        "chunk_count": chunk_count,
        "status": status,
        "content_preview": extracted_text[:PREVIEW_CHARS] if extracted_text else None,
    }
