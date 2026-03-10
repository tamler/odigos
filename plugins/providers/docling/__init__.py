"""Docling deep document extraction plugin.

Provides advanced PDF/document processing with table extraction,
figure detection, and layout analysis. Install with:
    pip install docling
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

try:
    from docling.document_converter import DocumentConverter
except ImportError:
    DocumentConverter = None


@dataclass
class ConvertedDocument:
    source: str
    content: str
    dl_doc: object = None


class DoclingProvider:
    """Deep document extraction using Docling.

    Converts documents (PDF, DOCX, PPTX, images) to markdown using docling.

    Note: docling's convert() is synchronous. Callers should run in a thread
    executor (asyncio.to_thread) to avoid blocking the event loop.
    """

    def __init__(self, max_content_chars: int = 8000) -> None:
        if DocumentConverter is None:
            raise ImportError(
                "Docling is not installed. Install with: pip install docling"
            )
        self.max_content_chars = max_content_chars
        self._converter = DocumentConverter()

    def convert(self, source: str) -> ConvertedDocument:
        """Convert a file path or URL to markdown."""
        result = self._converter.convert(source)
        doc = result.document
        content = doc.export_to_markdown()

        if len(content) > self.max_content_chars:
            content = content[: self.max_content_chars] + "\n\n[truncated]"

        return ConvertedDocument(source=source, content=content, dl_doc=doc)


def register(ctx):
    """Register the Docling provider as a document processor."""
    try:
        provider = DoclingProvider()
        ctx.register_provider("docling", provider)
        logger.info("Docling plugin loaded")
    except ImportError:
        logger.warning("Docling plugin skipped: docling package not installed")
