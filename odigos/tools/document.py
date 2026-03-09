from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from odigos.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from odigos.providers.docling import DoclingProvider

logger = logging.getLogger(__name__)


class DocTool(BaseTool):
    """Convert a document (PDF, DOCX, PPTX, image) to readable text."""

    name = "read_document"
    description = "Convert a document (PDF, DOCX, PPTX, image) to readable text. The document is automatically ingested into memory for future reference."
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path or URL to the document"},
        },
        "required": ["path"],
    }

    def __init__(self, provider: DoclingProvider, ingester=None) -> None:
        self.provider = provider
        self.ingester = ingester

    async def execute(self, params: dict) -> ToolResult:
        source = params.get("path") or params.get("url")
        if not source:
            return ToolResult(success=False, data="", error="No path or url provided")

        try:
            result = await asyncio.to_thread(self.provider.convert, source)

            # Ingest for future retrieval
            if self.ingester:
                filename = source.rsplit("/", 1)[-1] if "/" in source else source
                source_url = source if source.startswith(("http://", "https://")) else None
                await self.ingester.ingest(
                    text=result.content,
                    filename=filename,
                    source_url=source_url,
                    dl_doc=result.dl_doc,
                )

            return ToolResult(success=True, data=result.content)
        except Exception as e:
            logger.warning("Document conversion failed for %s: %s", source, e, exc_info=True)
            return ToolResult(success=False, data="", error=str(e))
