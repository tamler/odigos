from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from odigos.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from odigos.providers.markitdown import MarkItDownProvider

logger = logging.getLogger(__name__)


class DocTool(BaseTool):
    """Convert a document to readable text using MarkItDown (default) or Docling (deep mode)."""

    name = "process_document"
    description = (
        "Process a document (PDF, Word, Excel, HTML, image, etc.) and ingest it into memory. "
        "Pass 'deep: true' for complex PDFs with tables/figures (requires docling plugin)."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "File path or URL to process"},
            "deep": {"type": "boolean", "description": "Use deep extraction (docling) for complex documents. Default false."},
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

        deep = params.get("deep", False)

        # Use Docling for deep extraction if requested and available
        if deep and self.docling:
            return await self._convert_with_docling(source)

        if deep and not self.docling:
            logger.info("Deep extraction requested but docling plugin not available, using MarkItDown")

        # Default: use MarkItDown
        return await self._convert_with_markitdown(source)

    async def _convert_with_markitdown(self, source: str) -> ToolResult:
        if not self.markitdown:
            return ToolResult(success=False, data="", error="No document conversion provider available")

        try:
            if source.startswith(("http://", "https://")):
                content = await asyncio.to_thread(self.markitdown.convert_url, source)
            else:
                content = await asyncio.to_thread(self.markitdown.convert_file, source)
        except Exception as e:
            logger.warning("MarkItDown conversion failed for %s: %s", source, e, exc_info=True)
            return ToolResult(success=False, data="", error=str(e))

        await self._ingest(source, content)
        return ToolResult(success=True, data=content)

    async def _convert_with_docling(self, source: str) -> ToolResult:
        try:
            result = await asyncio.to_thread(self.docling.convert, source)
            content = result.content
            dl_doc = result.dl_doc
        except Exception as e:
            logger.warning("Docling conversion failed for %s: %s", source, e, exc_info=True)
            return ToolResult(success=False, data="", error=str(e))

        await self._ingest(source, content, dl_doc=dl_doc)
        return ToolResult(success=True, data=content)

    async def _ingest(self, source: str, content: str, dl_doc=None) -> None:
        if not self.ingester:
            return
        try:
            filename = source.rsplit("/", 1)[-1] if "/" in source else source
            source_url = source if source.startswith(("http://", "https://")) else None
            await self.ingester.ingest(
                text=content,
                filename=filename,
                source_url=source_url,
                dl_doc=dl_doc,
            )
        except Exception as e:
            logger.warning("Document ingestion failed for %s: %s", source, e, exc_info=True)
