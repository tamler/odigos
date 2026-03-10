"""Tests for the Docling plugin provider.

These tests mock the docling dependency so they run without it installed.
"""
import sys
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _mock_docling_import():
    """Provide a fake docling module so the plugin can be imported."""
    mock_module = MagicMock()
    with patch.dict(sys.modules, {"docling": mock_module, "docling.document_converter": mock_module}):
        yield mock_module


def _get_provider_class():
    """Import DoclingProvider from the plugin package."""
    # Force re-import so the mocked docling is picked up
    import importlib
    import plugins.providers.docling as docling_plugin
    importlib.reload(docling_plugin)
    return docling_plugin.DoclingProvider


class TestDoclingProvider:
    def test_convert_returns_markdown_content(self, _mock_docling_import):
        DoclingProvider = _get_provider_class()
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

    def test_convert_truncates_long_content(self, _mock_docling_import):
        DoclingProvider = _get_provider_class()
        provider = DoclingProvider(max_content_chars=50)
        mock_doc = MagicMock()
        mock_doc.document.export_to_markdown.return_value = "x" * 100
        mock_converter = MagicMock()
        mock_converter.convert.return_value = mock_doc
        with patch.object(provider, "_converter", mock_converter):
            result = provider.convert("/tmp/big.pdf")
        assert len(result.content) <= 50 + len("\n\n[truncated]")
        assert result.content.endswith("[truncated]")

    def test_convert_handles_url(self, _mock_docling_import):
        DoclingProvider = _get_provider_class()
        provider = DoclingProvider()
        mock_doc = MagicMock()
        mock_doc.document.export_to_markdown.return_value = "Web content"
        mock_converter = MagicMock()
        mock_converter.convert.return_value = mock_doc
        with patch.object(provider, "_converter", mock_converter):
            result = provider.convert("https://example.com/doc.pdf")
        assert result.source == "https://example.com/doc.pdf"
        mock_converter.convert.assert_called_once_with("https://example.com/doc.pdf")
