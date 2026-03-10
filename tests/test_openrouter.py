import httpx
import pytest
from unittest.mock import patch

from odigos.providers.llm import LLMClient


class TestGenerationId:
    @pytest.fixture
    def provider(self):
        return LLMClient(
            base_url="https://api.example.com/v1",
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
