from unittest.mock import MagicMock

from odigos.providers.docling import ConvertedDocument, DoclingProvider
from odigos.tools.document import DocTool


class TestDocTool:
    async def test_execute_with_path(self):
        mock_provider = MagicMock(spec=DoclingProvider)
        mock_provider.convert.return_value = ConvertedDocument(
            source="/tmp/test.pdf", content="# Document\n\nContent here."
        )
        tool = DocTool(provider=mock_provider)
        result = await tool.execute({"path": "/tmp/test.pdf"})
        assert result.success is True
        assert "Content here" in result.data
        mock_provider.convert.assert_called_once_with("/tmp/test.pdf")

    async def test_execute_with_url(self):
        mock_provider = MagicMock(spec=DoclingProvider)
        mock_provider.convert.return_value = ConvertedDocument(
            source="https://example.com/doc.pdf", content="Web doc content"
        )
        tool = DocTool(provider=mock_provider)
        result = await tool.execute({"url": "https://example.com/doc.pdf"})
        assert result.success is True
        assert "Web doc content" in result.data

    async def test_execute_with_no_source(self):
        mock_provider = MagicMock(spec=DoclingProvider)
        tool = DocTool(provider=mock_provider)
        result = await tool.execute({})
        assert result.success is False
        assert result.error is not None

    async def test_execute_handles_conversion_error(self):
        mock_provider = MagicMock(spec=DoclingProvider)
        mock_provider.convert.side_effect = Exception("Unsupported format")
        tool = DocTool(provider=mock_provider)
        result = await tool.execute({"path": "/tmp/bad.xyz"})
        assert result.success is False
        assert result.error is not None

    async def test_tool_name_and_description(self):
        mock_provider = MagicMock(spec=DoclingProvider)
        tool = DocTool(provider=mock_provider)
        assert tool.name == "read_document"
        assert "document" in tool.description.lower() or "PDF" in tool.description
