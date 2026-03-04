from unittest.mock import AsyncMock

import pytest

from odigos.providers.searxng import SearchResult
from odigos.tools.search import SearchTool


class TestSearchTool:
    @pytest.fixture
    def mock_searxng(self):
        provider = AsyncMock()
        provider.search.return_value = [
            SearchResult(
                title="Python Docs",
                url="https://docs.python.org",
                snippet="Official Python documentation.",
            ),
            SearchResult(
                title="Real Python", url="https://realpython.com", snippet="Python tutorials."
            ),
        ]
        return provider

    @pytest.fixture
    def tool(self, mock_searxng):
        return SearchTool(searxng=mock_searxng)

    async def test_tool_name(self, tool):
        assert tool.name == "web_search"

    async def test_execute_returns_formatted_results(self, tool, mock_searxng):
        result = await tool.execute({"query": "python docs"})

        assert result.success is True
        assert "Python Docs" in result.data
        assert "https://docs.python.org" in result.data
        assert "Official Python documentation." in result.data
        mock_searxng.search.assert_called_once_with("python docs")

    async def test_execute_missing_query(self, tool):
        result = await tool.execute({})

        assert result.success is False
        assert "query" in result.error.lower()

    async def test_execute_empty_results(self, tool, mock_searxng):
        mock_searxng.search.return_value = []

        result = await tool.execute({"query": "obscure query"})

        assert result.success is True
        assert "no results" in result.data.lower()
