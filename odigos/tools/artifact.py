"""Agent tool for creating downloadable artifacts (files for the user)."""

from __future__ import annotations

import logging
import mimetypes
import uuid
from datetime import datetime, timezone
from pathlib import Path

from odigos.db import Database
from odigos.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

ARTIFACTS_DIR = Path("data/artifacts")

# Content type mapping for common extensions
_CONTENT_TYPES = {
    ".csv": "text/csv",
    ".md": "text/markdown",
    ".json": "application/json",
    ".html": "text/html",
    ".txt": "text/plain",
    ".xml": "application/xml",
    ".yaml": "application/x-yaml",
    ".yml": "application/x-yaml",
}


class CreateArtifactTool(BaseTool):
    name = "create_artifact"
    description = (
        "Create a downloadable file for the user. Use this when the user asks you to "
        "generate a spreadsheet, document, report, data export, or any file they can download. "
        "Provide the filename (with extension) and the file content as a string. "
        "Supported formats: CSV, Markdown, JSON, HTML, TXT, XML, YAML."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "Filename with extension (e.g. 'report.csv', 'summary.md', 'data.json')",
            },
            "content": {
                "type": "string",
                "description": "The file content as a string",
            },
        },
        "required": ["filename", "content"],
    }

    def __init__(self, db: Database) -> None:
        self.db = db

    async def execute(self, params: dict) -> ToolResult:
        filename = params.get("filename", "").strip()
        content = params.get("content", "")
        conversation_id = params.get("_conversation_id")

        if not filename:
            return ToolResult(success=False, data="", error="Filename is required")

        # Sanitize filename
        filename = Path(filename).name  # Strip any path components
        if not filename or filename.startswith("."):
            return ToolResult(success=False, data="", error="Invalid filename")

        # Determine content type
        ext = Path(filename).suffix.lower()
        content_type = _CONTENT_TYPES.get(ext) or mimetypes.guess_type(filename)[0] or "application/octet-stream"

        # Create artifact
        artifact_id = str(uuid.uuid4())
        artifact_dir = ARTIFACTS_DIR / artifact_id
        artifact_dir.mkdir(parents=True, exist_ok=True)

        file_path = artifact_dir / filename
        file_path.write_text(content, encoding="utf-8")
        file_size = file_path.stat().st_size

        # Register in database
        now = datetime.now(timezone.utc).isoformat()
        await self.db.execute(
            "INSERT INTO artifacts (id, conversation_id, filename, content_type, file_size, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (artifact_id, conversation_id, filename, content_type, file_size, now),
        )

        logger.info("Created artifact %s: %s (%d bytes)", artifact_id[:8], filename, file_size)

        return ToolResult(
            success=True,
            data=f"Created file: {filename} ({file_size} bytes). The user can download it from the artifacts panel.",
            side_effect={
                "artifact": {
                    "id": artifact_id,
                    "filename": filename,
                    "content_type": content_type,
                    "file_size": file_size,
                    "download_url": f"/api/artifacts/{artifact_id}/download",
                },
            },
        )
