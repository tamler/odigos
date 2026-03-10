import pytest
from odigos.memory.chunking import ChunkingService


class TestChunkingService:
    def test_short_text_not_chunked(self):
        """Short text (<500 tokens) is returned as-is."""
        cs = ChunkingService()
        result = cs.chunk("Hello world, this is a short message.", content_type="message")
        assert result == ["Hello world, this is a short message."]

    def test_long_text_is_chunked(self):
        """Long text is split into multiple chunks."""
        cs = ChunkingService()
        long_text = "This is a sentence about dogs. " * 200
        result = cs.chunk(long_text, content_type="message")
        assert len(result) > 1
        combined = " ".join(result)
        assert "dogs" in combined

    def test_document_chunking(self):
        """Document content type uses recursive chunking."""
        cs = ChunkingService()
        doc = (
            "# Title\n\nFirst paragraph about topic A with enough detail to make it substantial. "
            "This paragraph discusses the intricacies of the subject matter in great depth.\n\n"
            "## Section 2\n\nSecond paragraph about topic B covering different ground entirely. "
            "We explore the nuances and implications of this secondary theme at length.\n\n"
        ) * 50
        result = cs.chunk(doc, content_type="document")
        assert len(result) > 1

    def test_code_chunking(self):
        """Code content type respects structural boundaries."""
        cs = ChunkingService()
        code = '''
def foo():
    return 1

def bar():
    return 2

class Baz:
    def method(self):
        return 3
''' * 20
        result = cs.chunk(code, content_type="code")
        assert len(result) > 1

    def test_empty_text_returns_empty(self):
        """Empty string returns empty list."""
        cs = ChunkingService()
        assert cs.chunk("", content_type="message") == []

    def test_whitespace_only_returns_empty(self):
        """Whitespace-only text returns empty list."""
        cs = ChunkingService()
        assert cs.chunk("   \n\n  ", content_type="message") == []
