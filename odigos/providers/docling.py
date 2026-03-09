from __future__ import annotations

import logging
from dataclasses import dataclass

from docling.document_converter import DocumentConverter

logger = logging.getLogger(__name__)


@dataclass
class ConvertedDocument:
    source: str
    content: str
    dl_doc: object = None


class DoclingProvider:
    """Converts documents (PDF, DOCX, PPTX, images) to markdown using docling.

    Note: docling's convert() is synchronous. Callers should run in a thread
    executor (asyncio.to_thread) to avoid blocking the event loop.
    """

    def __init__(self, max_content_chars: int = 8000) -> None:
        self.max_content_chars = max_content_chars
        self._converter = DocumentConverter()

    def convert(self, source: str) -> ConvertedDocument:
        """Convert a file path or URL to markdown."""
        result = self._converter.convert(source)
        dl_doc = result.document
        content = dl_doc.export_to_markdown()

        if len(content) > self.max_content_chars:
            content = content[: self.max_content_chars] + "\n\n[truncated]"

        return ConvertedDocument(source=source, content=content, dl_doc=dl_doc)
