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
    description = "Convert a document (PDF, DOCX, PPTX, image) to readable text."

    def __init__(self, provider: DoclingProvider) -> None:
        self.provider = provider

    async def execute(self, params: dict) -> ToolResult:
        source = params.get("path") or params.get("url")
        if not source:
            return ToolResult(success=False, data="", error="No path or url provided")

        try:
            result = await asyncio.to_thread(self.provider.convert, source)
            return ToolResult(success=True, data=result.content)
        except Exception as e:
            logger.warning("Document conversion failed for %s: %s", source, e, exc_info=True)
            return ToolResult(success=False, data="", error=str(e))
