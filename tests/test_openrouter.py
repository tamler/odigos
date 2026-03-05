import httpx
import pytest
from unittest.mock import AsyncMock, patch

from odigos.providers.openrouter import OPENROUTER_GENERATION_URL, OpenRouterProvider


class TestOpenRouterGenerationId:
    @pytest.fixture
    def provider(self):
        return OpenRouterProvider(
            api_key="test-key",
            default_model="test/model",
            fallback_model="test/fallback",
        )

    async def test_extracts_generation_id(self, provider):
        """Provider extracts generation ID from response."""
        mock_response = httpx.Response(
            200,
            json={
                "id": "gen-abc123",
                "choices": [{"message": {"content": "Hello"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                "model": "test/model",
            },
        )
        with patch.object(provider._client, "post", return_value=mock_response):
            result = await provider.complete([{"role": "user", "content": "Hi"}])

        assert result.generation_id == "gen-abc123"

    async def test_generation_id_none_when_missing(self, provider):
        """Provider sets generation_id to None when not in response."""
        mock_response = httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "Hello"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )
        with patch.object(provider._client, "post", return_value=mock_response):
            result = await provider.complete([{"role": "user", "content": "Hi"}])

        assert result.generation_id is None


class TestFetchGenerationCost:
    @pytest.fixture
    def provider(self):
        return OpenRouterProvider(
            api_key="test-key",
            default_model="test/model",
            fallback_model="test/fallback",
        )

    async def test_fetch_generation_cost_returns_total_cost(self, provider):
        """Returns total_cost from generation endpoint."""
        mock_response = httpx.Response(
            200,
            json={"data": {"total_cost": 0.00042}},
        )
        with patch.object(provider._client, "get", return_value=mock_response) as mock_get:
            result = await provider.fetch_generation_cost("gen-abc123")

        mock_get.assert_called_once_with(
            OPENROUTER_GENERATION_URL,
            params={"id": "gen-abc123"},
        )
        assert result == 0.00042

    async def test_fetch_generation_cost_returns_none_on_error(self, provider):
        """Returns None when the HTTP request fails."""
        mock_get = AsyncMock(side_effect=httpx.HTTPError("connection failed"))
        with patch.object(provider._client, "get", mock_get):
            result = await provider.fetch_generation_cost("gen-abc123")

        assert result is None

    async def test_fetch_generation_cost_returns_none_on_missing_data(self, provider):
        """Returns None when total_cost is absent from the response."""
        mock_response = httpx.Response(
            200,
            json={"data": {}},
        )
        with patch.object(provider._client, "get", return_value=mock_response):
            result = await provider.fetch_generation_cost("gen-abc123")

        assert result is None
