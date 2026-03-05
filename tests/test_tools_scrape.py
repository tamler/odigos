from unittest.mock import AsyncMock

import pytest

from odigos.providers.scraper import ScrapedPage
from odigos.tools.scrape import ScrapeTool


class TestScrapeTool:
    def test_tool_metadata(self):
        mock_scraper = AsyncMock()
        tool = ScrapeTool(scraper=mock_scraper)
        assert tool.name == "read_page"
        assert "read" in tool.description.lower() or "page" in tool.description.lower()

    async def test_execute_success(self):
        mock_scraper = AsyncMock()
        mock_scraper.scrape.return_value = ScrapedPage(
            url="https://example.com",
            title="Example Page",
            content="This is the main content of the page.",
        )
        tool = ScrapeTool(scraper=mock_scraper)

        result = await tool.execute({"url": "https://example.com"})

        assert result.success is True
        assert "Example Page" in result.data
        assert "main content" in result.data
        mock_scraper.scrape.assert_called_once_with("https://example.com")

    async def test_execute_empty_content(self):
        mock_scraper = AsyncMock()
        mock_scraper.scrape.return_value = ScrapedPage(
            url="https://example.com/broken", title="", content=""
        )
        tool = ScrapeTool(scraper=mock_scraper)

        result = await tool.execute({"url": "https://example.com/broken"})

        assert result.success is True
        assert "could not extract" in result.data.lower()

    async def test_execute_missing_url(self):
        mock_scraper = AsyncMock()
        tool = ScrapeTool(scraper=mock_scraper)

        result = await tool.execute({})

        assert result.success is False
        assert "url" in result.error.lower()
