from unittest.mock import AsyncMock

from odigos.providers.scraper import ScrapedPage
from odigos.tools.scrape import ScrapeTool


class TestScrapeToolTier:
    async def test_passes_tier_to_scraper(self):
        mock_scraper = AsyncMock()
        mock_scraper.scrape.return_value = ScrapedPage(
            url="https://example.com", title="Test", content="Content"
        )
        tool = ScrapeTool(scraper=mock_scraper)
        result = await tool.execute({"url": "https://example.com", "tier": "browser"})
        mock_scraper.scrape.assert_called_once_with("https://example.com", tier="browser")
        assert result.success is True

    async def test_defaults_to_standard_tier(self):
        mock_scraper = AsyncMock()
        mock_scraper.scrape.return_value = ScrapedPage(
            url="https://example.com", title="Test", content="Content"
        )
        tool = ScrapeTool(scraper=mock_scraper)
        result = await tool.execute({"url": "https://example.com"})
        mock_scraper.scrape.assert_called_once_with("https://example.com", tier="standard")
        assert result.success is True
