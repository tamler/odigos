"""File upload endpoint."""

import os
import secrets

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from odigos.api.deps import get_upload_dir, require_api_key

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB

router = APIRouter(
    prefix="/api",
    dependencies=[Depends(require_api_key)],
)


@router.post("/upload")
async def upload_file(file: UploadFile, upload_dir: str = Depends(get_upload_dir)):
    """Upload a file, store it, return a reference ID."""
    os.makedirs(upload_dir, exist_ok=True)

    file_id = secrets.token_hex(8)
    safe_name = os.path.basename(file.filename or "upload")
    dest = os.path.join(upload_dir, f"{file_id}_{safe_name}")

    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (50 MB max)")

    with open(dest, "wb") as f:
        f.write(content)

    return {
        "id": file_id,
        "filename": file.filename,
        "size": len(content),
    }
