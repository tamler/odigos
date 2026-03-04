from unittest.mock import AsyncMock

import httpx
import pytest

from odigos.providers.searxng import SearxngProvider


class TestSearxngProvider:
    @pytest.fixture
    def provider(self):
        return SearxngProvider(
            url="https://search.example.com",
            username="testuser",
            password="testpass",
        )

    async def test_search_returns_results(self, provider):
        """Search returns a list of SearchResult from SearXNG JSON API."""
        mock_response = httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Python Docs",
                        "url": "https://docs.python.org",
                        "content": "Official Python documentation.",
                    },
                    {
                        "title": "Real Python",
                        "url": "https://realpython.com",
                        "content": "Python tutorials and articles.",
                    },
                ]
            },
        )
        provider._client = AsyncMock()
        provider._client.get = AsyncMock(return_value=mock_response)

        results = await provider.search("python documentation")

        assert len(results) == 2
        assert results[0].title == "Python Docs"
        assert results[0].url == "https://docs.python.org"
        assert results[0].snippet == "Official Python documentation."
        provider._client.get.assert_called_once()

    async def test_search_respects_num_results(self, provider):
        """Search limits results to num_results parameter."""
        mock_response = httpx.Response(
            200,
            json={
                "results": [
                    {"title": f"Result {i}", "url": f"https://example.com/{i}", "content": f"Snippet {i}"}
                    for i in range(10)
                ]
            },
        )
        provider._client = AsyncMock()
        provider._client.get = AsyncMock(return_value=mock_response)

        results = await provider.search("test", num_results=3)

        assert len(results) == 3

    async def test_search_returns_empty_on_error(self, provider):
        """Search returns empty list on HTTP error instead of raising."""
        mock_response = httpx.Response(500, text="Internal Server Error")
        provider._client = AsyncMock()
        provider._client.get = AsyncMock(return_value=mock_response)

        results = await provider.search("failing query")

        assert results == []

    async def test_search_returns_empty_on_network_error(self, provider):
        """Search returns empty list on network errors."""
        provider._client = AsyncMock()
        provider._client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

        results = await provider.search("failing query")

        assert results == []
