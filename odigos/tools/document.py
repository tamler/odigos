from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from odigos.tools.base import BaseTool, ToolResult
from odigos.storage import FILES_DIR

logger = logging.getLogger(__name__)

_ALLOWED_DIR = FILES_DIR.resolve()


class DocTool(BaseTool):
    """Convert a document to readable text using MarkItDown (default) or Docling (deep mode)."""

    name = "process_document"
    category = "analysis"
    description = (
        "Process a document (PDF, Word, Excel, HTML, image, etc.) and ingest it into memory. "
        "Use for extracting text from rich document formats. "
        "Do not use for plain text files — use manage_files read operation instead."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "File path or URL to process"},
            "deep": {"type": "string", "enum": ["true", "false"], "description": "Use deep extraction (docling) for complex documents. Default 'false'."},
        },
        "required": ["source"],
    }

    def __init__(self, markitdown_provider=None, ingester=None, docling_provider=None) -> None:
        self.markitdown = markitdown_provider
        self.ingester = ingester
        self.docling = docling_provider

    async def execute(self, params: dict) -> ToolResult:
        source = params.get("source") or params.get("path") or params.get("url")
        if not source:
            return ToolResult(success=False, data="", error="No source provided")

        deep = str(params.get("deep", "false")).lower() == "true"

        # Use Docling for deep extraction if requested and available
        if deep and self.docling:
            return await self._convert_with_docling(source)

        if deep and not self.docling:
            logger.info("Deep extraction requested but docling plugin not available, using MarkItDown")

        # Default: use MarkItDown
        return await self._convert_with_markitdown(source)

    def _validate_local_path(self, source: str) -> str | None:
        """Resolve a local file path and verify it's within the allowed directory."""
        resolved = Path(source).resolve()
        try:
            resolved.relative_to(_ALLOWED_DIR)
        except ValueError:
            return None
        return str(resolved)

    async def _convert_with_markitdown(self, source: str) -> ToolResult:
        if not self.markitdown:
            return ToolResult(success=False, data="", error="No document conversion provider available")

        try:
            if source.startswith(("http://", "https://")):
                content = await asyncio.to_thread(self.markitdown.convert_url, source)
            else:
                safe = self._validate_local_path(source)
                if not safe:
                    return ToolResult(success=False, data="", error="Path outside allowed directory")
                content = await asyncio.to_thread(self.markitdown.convert_file, safe)
        except Exception as e:
            logger.warning("MarkItDown conversion failed for %s: %s", source, e, exc_info=True)
            return ToolResult(success=False, data="", error=str(e))

        await self._ingest(source, content)
        return ToolResult(success=True, data=content)

    async def _convert_with_docling(self, source: str) -> ToolResult:
        try:
            if not source.startswith(("http://", "https://")):
                safe = self._validate_local_path(source)
                if not safe:
                    return ToolResult(success=False, data="", error="Path outside allowed directory")
                source = safe
            result = await asyncio.to_thread(self.docling.convert, source)
            content = result.content
        except Exception as e:
            logger.warning("Docling conversion failed for %s: %s", source, e, exc_info=True)
            return ToolResult(success=False, data="", error=str(e))

        await self._ingest(source, content)
        return ToolResult(success=True, data=content)

    async def _ingest(self, source: str, content: str) -> None:
        if not self.ingester:
            return
        try:
            import hashlib
            import os

            filename = source.rsplit("/", 1)[-1] if "/" in source else source
            source_url = source if source.startswith(("http://", "https://")) else None
            file_path = source if not source.startswith(("http://", "https://")) else None
            file_size = os.path.getsize(source) if file_path and os.path.exists(source) else None
            content_hash = hashlib.sha256(content.encode()).hexdigest()

            await self.ingester.ingest(
                text=content,
                filename=filename,
                source_url=source_url,
                file_path=file_path,
                file_size=file_size,
                content_hash=content_hash,
            )
        except Exception as e:
            logger.warning("Document ingestion failed for %s: %s", source, e, exc_info=True)
