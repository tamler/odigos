import pytest
from unittest.mock import AsyncMock, MagicMock
from odigos.tools.document import DocTool


class TestDocToolMarkItDown:
    async def test_uses_markitdown_by_default(self):
        """DocTool uses MarkItDown when no deep flag."""
        markitdown = MagicMock()
        markitdown.convert_file.return_value = "# Converted\n\nContent here."

        ingester = AsyncMock()
        ingester.ingest.return_value = "doc-id"

        tool = DocTool(markitdown_provider=markitdown, ingester=ingester)
        result = await tool.execute({"source": "/tmp/test.pdf"})

        assert result.success
        markitdown.convert_file.assert_called_once()

    async def test_uses_docling_when_deep(self):
        """DocTool uses Docling for deep extraction when available."""
        markitdown = MagicMock()
        docling = MagicMock()
        docling.convert.return_value = MagicMock(content="Full content", dl_doc=MagicMock())

        ingester = AsyncMock()
        ingester.ingest.return_value = "doc-id"

        tool = DocTool(
            markitdown_provider=markitdown,
            ingester=ingester,
            docling_provider=docling,
        )
        result = await tool.execute({"source": "/tmp/test.pdf", "deep": True})

        assert result.success
        docling.convert.assert_called_once()
        markitdown.convert_file.assert_not_called()

    async def test_falls_back_to_markitdown_when_no_docling(self):
        """DocTool uses MarkItDown even when deep=True if Docling not available."""
        markitdown = MagicMock()
        markitdown.convert_file.return_value = "Content"

        ingester = AsyncMock()

        tool = DocTool(markitdown_provider=markitdown, ingester=ingester)
        result = await tool.execute({"source": "/tmp/test.pdf", "deep": True})

        assert result.success
        markitdown.convert_file.assert_called_once()

    async def test_no_source_returns_error(self):
        """Missing source parameter returns error."""
        tool = DocTool(markitdown_provider=MagicMock())
        result = await tool.execute({})
        assert not result.success
        assert "source" in result.error.lower() or "No" in result.error

    async def test_url_uses_convert_url(self):
        """URLs are dispatched to convert_url."""
        markitdown = MagicMock()
        markitdown.convert_url.return_value = "Web content"

        tool = DocTool(markitdown_provider=markitdown)
        result = await tool.execute({"source": "https://example.com/doc.pdf"})

        assert result.success
        markitdown.convert_url.assert_called_once_with("https://example.com/doc.pdf")
        markitdown.convert_file.assert_not_called()

    async def test_no_provider_returns_error(self):
        """No markitdown provider returns error."""
        tool = DocTool()
        result = await tool.execute({"source": "/tmp/test.pdf"})
        assert not result.success
        assert "provider" in result.error.lower() or "available" in result.error.lower()

    async def test_tool_name_and_description(self):
        """Tool has updated name and description."""
        tool = DocTool(markitdown_provider=MagicMock())
        assert tool.name == "process_document"
        assert "document" in tool.description.lower()

    async def test_backward_compat_path_param(self):
        """Accepts 'path' param for backward compatibility."""
        markitdown = MagicMock()
        markitdown.convert_file.return_value = "Content"

        tool = DocTool(markitdown_provider=markitdown)
        result = await tool.execute({"path": "/tmp/test.pdf"})

        assert result.success
        markitdown.convert_file.assert_called_once()
