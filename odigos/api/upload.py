"""File upload endpoint."""

import os
import secrets

from fastapi import APIRouter, Depends, UploadFile

from odigos.api.deps import get_upload_dir, require_api_key

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

    content = await file.read()
    with open(dest, "wb") as f:
        f.write(content)

    return {
        "id": file_id,
        "filename": file.filename,
        "size": len(content),
        "path": dest,
    }
