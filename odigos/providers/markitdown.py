from __future__ import annotations

import logging
from pathlib import Path

from markitdown import MarkItDown

logger = logging.getLogger(__name__)


class MarkItDownProvider:
    """Lightweight document-to-Markdown conversion via Microsoft MarkItDown.

    Supports PDF, Word, PowerPoint, Excel, HTML, images (OCR), audio,
    YouTube URLs, CSV, JSON, XML, ZIP, and EPUB.

    Note: convert operations are synchronous. Callers should run in a thread
    executor (asyncio.to_thread) to avoid blocking the event loop.
    """

    def __init__(self) -> None:
        self._converter = MarkItDown()

    def convert_file(self, file_path: str) -> str:
        """Convert a file to Markdown.

        Raises FileNotFoundError if file doesn't exist.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        result = self._converter.convert(file_path)
        return result.text_content

    def convert_text(self, text: str) -> str:
        """Pass-through for plain text (already Markdown-compatible)."""
        return text

    def convert_url(self, url: str) -> str:
        """Convert a URL's content to Markdown."""
        result = self._converter.convert_url(url)
        return result.text_content
