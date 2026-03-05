from unittest.mock import MagicMock, patch

from odigos.providers.scraper import ScrapedPage, ScraperProvider


class TestScraperProviderNew:
    async def test_scrape_standard_tier_uses_stealthy(self):
        scraper = ScraperProvider()
        mock_adaptor = MagicMock()
        mock_adaptor.css.return_value.get.return_value = "Test Title"
        mock_content = MagicMock()
        mock_content.get_all_text.return_value = "Article content"
        with patch.object(ScraperProvider, "_fetch", return_value=mock_adaptor) as mock_fetch:
            result = await scraper.scrape("https://example.com")
            assert isinstance(result, ScrapedPage)
            assert result.url == "https://example.com"
            mock_fetch.assert_called_once_with("https://example.com", "standard")

    async def test_scrape_browser_tier_uses_playwright(self):
        scraper = ScraperProvider()
        mock_adaptor = MagicMock()
        mock_adaptor.css.return_value.get.return_value = "JS Page"
        with patch.object(ScraperProvider, "_fetch", return_value=mock_adaptor) as mock_fetch:
            await scraper.scrape("https://example.com", tier="browser")
            mock_fetch.assert_called_once_with("https://example.com", "browser")

    async def test_scrape_returns_empty_on_fetch_failure(self):
        scraper = ScraperProvider()
        with patch.object(
            ScraperProvider, "_fetch", side_effect=Exception("Connection failed")
        ):
            result = await scraper.scrape("https://bad.example.com")
        assert result.content == ""
        assert result.title == ""

    async def test_scrape_truncates_long_content(self):
        scraper = ScraperProvider(max_content_chars=50)
        mock_adaptor = MagicMock()
        mock_adaptor.css.return_value.get.return_value = "Title"
        mock_content = MagicMock()
        mock_content.get_all_text.return_value = "x" * 100
        mock_adaptor.css.side_effect = [
            MagicMock(get=MagicMock(return_value="Title")),
            [mock_content],
        ]
        with patch.object(ScraperProvider, "_fetch", return_value=mock_adaptor):
            result = await scraper.scrape("https://example.com")
        assert result.content.endswith("[truncated]")
        assert len(result.content) < 100

    async def test_close_is_noop(self):
        scraper = ScraperProvider()
        await scraper.close()  # Should not raise

    def test_fetch_static_method_standard(self):
        with patch("odigos.providers.scraper.StealthyFetcher") as mock:
            mock.fetch.return_value = MagicMock()
            ScraperProvider._fetch("https://example.com", "standard")
            mock.fetch.assert_called_once_with("https://example.com")

    def test_fetch_static_method_browser(self):
        with patch("odigos.providers.scraper.DynamicFetcher") as mock:
            mock.fetch.return_value = MagicMock()
            ScraperProvider._fetch("https://example.com", "browser")
            mock.fetch.assert_called_once_with("https://example.com")
