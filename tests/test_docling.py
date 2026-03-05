from unittest.mock import MagicMock, patch

from odigos.providers.docling import DoclingProvider


class TestDoclingProvider:
    def test_convert_returns_markdown_content(self):
        provider = DoclingProvider(max_content_chars=8000)
        mock_doc = MagicMock()
        mock_doc.document.export_to_markdown.return_value = "# Title\n\nSome content here."
        mock_converter = MagicMock()
        mock_converter.convert.return_value = mock_doc
        with patch.object(provider, "_converter", mock_converter):
            result = provider.convert("/tmp/test.pdf")
        assert result.content == "# Title\n\nSome content here."
        assert result.source == "/tmp/test.pdf"
        mock_converter.convert.assert_called_once_with("/tmp/test.pdf")

    def test_convert_truncates_long_content(self):
        provider = DoclingProvider(max_content_chars=50)
        mock_doc = MagicMock()
        mock_doc.document.export_to_markdown.return_value = "x" * 100
        mock_converter = MagicMock()
        mock_converter.convert.return_value = mock_doc
        with patch.object(provider, "_converter", mock_converter):
            result = provider.convert("/tmp/big.pdf")
        assert len(result.content) <= 50 + len("\n\n[truncated]")
        assert result.content.endswith("[truncated]")

    def test_convert_handles_url(self):
        provider = DoclingProvider()
        mock_doc = MagicMock()
        mock_doc.document.export_to_markdown.return_value = "Web content"
        mock_converter = MagicMock()
        mock_converter.convert.return_value = mock_doc
        with patch.object(provider, "_converter", mock_converter):
            result = provider.convert("https://example.com/doc.pdf")
        assert result.source == "https://example.com/doc.pdf"
        mock_converter.convert.assert_called_once_with("https://example.com/doc.pdf")
