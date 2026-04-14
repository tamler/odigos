import httpx
import pytest
from unittest.mock import patch

from odigos.config import ModelConfig, ProviderConfig
from odigos.providers.llm import LLMClient


class TestGenerationId:
    @pytest.fixture
    def provider(self):
        return LLMClient(
            providers={"test": ProviderConfig(base_url="https://api.example.com/v1", api_key="test-key")},
            models={
                "primary": ModelConfig(provider="test", id="test/model"),
                "fallback": ModelConfig(provider="test", id="test/fallback"),
            },
            routing={"fast": "primary", "fallback": "fallback"},
        )

    async def test_extracts_generation_id(self, provider):
        mock_response = httpx.Response(
            200,
            json={
                "id": "gen-abc123",
                "choices": [{"message": {"content": "Hello"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                "model": "test/model",
            },
        )
        with patch.object(provider._clients["test"], "post", return_value=mock_response):
            result = await provider.complete([{"role": "user", "content": "Hi"}])
        assert result.generation_id == "gen-abc123"

    async def test_generation_id_none_when_missing(self, provider):
        mock_response = httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "Hello"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )
        with patch.object(provider._clients["test"], "post", return_value=mock_response):
            result = await provider.complete([{"role": "user", "content": "Hi"}])
        assert result.generation_id is None
