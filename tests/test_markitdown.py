import pytest
from odigos.providers.markitdown import MarkItDownProvider


class TestMarkItDownProvider:
    def test_convert_text(self):
        """Convert plain text to markdown."""
        provider = MarkItDownProvider()
        result = provider.convert_text("Hello world")
        assert "Hello" in result

    def test_convert_html(self, tmp_path):
        """Convert HTML file to markdown."""
        html = tmp_path / "test.html"
        html.write_text("<h1>Title</h1><p>Content here.</p>")

        provider = MarkItDownProvider()
        result = provider.convert_file(str(html))
        assert "Title" in result
        assert "Content" in result

    def test_convert_nonexistent_file_raises(self):
        """Converting a nonexistent file raises FileNotFoundError."""
        provider = MarkItDownProvider()
        with pytest.raises(FileNotFoundError):
            provider.convert_file("/nonexistent/file.pdf")
