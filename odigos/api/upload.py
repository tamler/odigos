"""File upload endpoint with auto-ingestion into agent memory."""

import asyncio
import hashlib
import logging
import os
import secrets

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile

from odigos.tools.transcribe import AUDIO_EXTENSIONS

from odigos.api.deps import get_db, get_doc_ingester, get_markitdown, get_upload_dir, require_auth
from odigos.db import Database
from odigos.memory.ingester import DocumentIngester
from odigos.providers.markitdown import MarkItDownProvider

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB


def is_audio_file(filename: str) -> bool:
    """Check if a filename has an audio extension."""
    if not filename:
        return False
    ext = os.path.splitext(filename.lower())[1]
    return ext in AUDIO_EXTENSIONS
PREVIEW_CHARS = 2000

router = APIRouter(
    prefix="/api",
    dependencies=[Depends(require_auth)],
)


@router.post("/upload")
async def upload_file(
    request: Request,
    file: UploadFile,
    upload_dir: str = Depends(get_upload_dir),
    db: Database = Depends(get_db),
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

    # Extract text — use STT for audio files, MarkItDown for everything else
    extracted_text = None
    chunk_count = 0
    status = "failed"
    doc_id = None

    stt_provider = None
    plugin_context = getattr(request.app.state, "plugin_context", None)
    if plugin_context:
        stt_provider = plugin_context.get_provider("stt")

    if is_audio_file(safe_name) and stt_provider:
        try:
            extracted_text = await asyncio.to_thread(stt_provider.transcribe_file, dest)
        except Exception:
            logger.warning("Audio transcription failed for %s", safe_name, exc_info=True)
    else:
        try:
            extracted_text = await asyncio.to_thread(markitdown.convert_file, dest)
        except Exception:
            logger.warning("Text extraction failed for %s", safe_name, exc_info=True)

    # Soft limit check
    storage_warning = None
    chunk_row = await db.fetch_one("SELECT SUM(chunk_count) as total FROM documents")
    total_chunks = chunk_row["total"] if chunk_row and chunk_row["total"] else 0
    if total_chunks > 200000:
        storage_warning = "Storage is near capacity. Consider deleting unused documents in Settings > Documents."

    if extracted_text:
        try:
            doc_id = await ingester.ingest(
                text=extracted_text,
                filename=safe_name,
                file_path=dest,
                file_size=len(content),
                content_hash=content_hash,
                force=True,  # User uploaded — always re-process with current chunk settings
            )
            row = await ingester.get_document_metadata(doc_id)
            if row:
                chunk_count = row["chunk_count"]
                status = row["status"]
        except Exception:
            logger.warning("Ingestion failed for %s", safe_name, exc_info=True)
            status = "failed"

    result = {
        "id": file_id,
        "document_id": doc_id,
        "filename": file.filename,
        "size": len(content),
        "chunk_count": chunk_count,
        "status": status,
        "content_preview": extracted_text[:PREVIEW_CHARS] if extracted_text else None,
    }
    if storage_warning:
        result["storage_warning"] = storage_warning
    return result
