from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from odigos.providers.scraper import ScrapedPage, ScraperProvider


class TestScrapedPage:
    def test_dataclass_fields(self):
        page = ScrapedPage(url="https://example.com", title="Example", content="Hello world")
        assert page.url == "https://example.com"
        assert page.title == "Example"
        assert page.content == "Hello world"
        assert page.scraped_at is not None

    def test_default_scraped_at(self):
        page = ScrapedPage(url="https://example.com", title="", content="")
        assert isinstance(page.scraped_at, str)
        assert len(page.scraped_at) > 0


class TestScraperProvider:
    async def test_scrape_success(self):
        html = "<html><head><title>Test Page</title></head><body><article><p>Main content here.</p></article></body></html>"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = html
        mock_response.raise_for_status = MagicMock()

        provider = ScraperProvider()
        with patch.object(provider._client, "get", new_callable=AsyncMock, return_value=mock_response):
            result = await provider.scrape("https://example.com")

        assert result.url == "https://example.com"
        assert result.title == "Test Page"
        assert "Main content" in result.content

    async def test_scrape_truncates_long_content(self):
        long_text = "word " * 2000
        html = f"<html><head><title>Long</title></head><body><p>{long_text}</p></body></html>"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = html
        mock_response.raise_for_status = MagicMock()

        provider = ScraperProvider(max_content_chars=100)
        with patch.object(provider._client, "get", new_callable=AsyncMock, return_value=mock_response):
            result = await provider.scrape("https://example.com")

        assert len(result.content) <= 130
        assert "[truncated]" in result.content

    async def test_scrape_http_error(self):
        provider = ScraperProvider()
        mock_get = AsyncMock(side_effect=Exception("Connection refused"))
        with patch.object(provider._client, "get", mock_get):
            result = await provider.scrape("https://example.com/missing")

        assert result.url == "https://example.com/missing"
        assert result.content == ""

    async def test_scrape_falls_back_to_body(self):
        """When no content selectors match, falls back to body text."""
        html = "<html><head><title>Simple</title></head><body><div><p>Body text only.</p></div></body></html>"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = html
        mock_response.raise_for_status = MagicMock()

        provider = ScraperProvider()
        with patch.object(provider._client, "get", new_callable=AsyncMock, return_value=mock_response):
            result = await provider.scrape("https://example.com")

        assert "Body text only" in result.content

    async def test_close(self):
        provider = ScraperProvider()
        with patch.object(provider._client, "aclose", new_callable=AsyncMock) as mock_close:
            await provider.close()
            mock_close.assert_called_once()
