from __future__ import annotations

import logging

import tiktoken

logger = logging.getLogger(__name__)

_tokenizer = tiktoken.get_encoding("cl100k_base")
SHORT_TEXT_THRESHOLD = 500  # tokens


class ChunkingService:
    """Unified chunking layer using Chonkie.

    Routes text to the appropriate chunker based on content_type:
    - "message": SemanticChunker for long messages, as-is for short ones
    - "document": RecursiveChunker for structured documents
    - "code": CodeChunker for source code
    - "text": SentenceChunker for plain text (e.g. MarkItDown output)
    """

    def __init__(self, chunk_size: int = 256, chunk_overlap: int = 50) -> None:
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._chunkers: dict = {}

    def _get_chunker(self, content_type: str):
        """Lazy-load chunkers to avoid import cost at startup."""
        if content_type not in self._chunkers:
            if content_type == "message":
                from chonkie import SemanticChunker

                self._chunkers[content_type] = SemanticChunker(
                    chunk_size=self._chunk_size,
                )
            elif content_type == "document":
                from chonkie import RecursiveChunker

                self._chunkers[content_type] = RecursiveChunker(
                    chunk_size=self._chunk_size,
                )
            elif content_type == "code":
                from chonkie import CodeChunker

                self._chunkers[content_type] = CodeChunker(
                    chunk_size=self._chunk_size,
                )
            else:  # "text" or fallback
                from chonkie import SentenceChunker

                self._chunkers[content_type] = SentenceChunker(
                    chunk_size=self._chunk_size,
                    chunk_overlap=self._chunk_overlap,
                )
        return self._chunkers[content_type]

    def chunk(self, text: str, content_type: str = "message") -> list[str]:
        """Split text into chunks appropriate for the content type.

        Returns the text as-is (single-element list) if it's short enough.
        Returns empty list for empty/whitespace-only text.
        """
        if not text or not text.strip():
            return []

        text = text.strip()

        # Short text doesn't need chunking
        token_count = len(_tokenizer.encode(text, disallowed_special=()))
        if token_count <= SHORT_TEXT_THRESHOLD:
            return [text]

        try:
            chunker = self._get_chunker(content_type)
            chunks = chunker.chunk(text)
            return [c.text for c in chunks if c.text.strip()]
        except Exception:
            logger.warning("Chunking failed, falling back to paragraph split", exc_info=True)
            paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
            return paragraphs if paragraphs else [text]
