from unittest.mock import AsyncMock, patch

import httpx
import pytest

from odigos.providers.embeddings import EmbeddingProvider


@pytest.fixture
def provider():
    return EmbeddingProvider(api_key="test-key")


class TestEmbeddingProvider:
    async def test_embed_single_text(self, provider: EmbeddingProvider):
        """Embeds a single text string and returns a 1536-d vector."""
        mock_response = httpx.Response(
            200,
            json={
                "data": [{"embedding": [0.1] * 1536}],
                "usage": {"prompt_tokens": 5, "total_tokens": 5},
            },
        )

        with patch.object(
            provider._client, "post", new_callable=AsyncMock, return_value=mock_response
        ):
            result = await provider.embed("Hello world")

        assert len(result) == 1536
        assert result[0] == pytest.approx(0.1)

    async def test_embed_batch(self, provider: EmbeddingProvider):
        """Embeds a list of texts and returns a list of vectors."""
        mock_response = httpx.Response(
            200,
            json={
                "data": [
                    {"embedding": [0.1] * 1536},
                    {"embedding": [0.2] * 1536},
                ],
                "usage": {"prompt_tokens": 10, "total_tokens": 10},
            },
        )

        with patch.object(
            provider._client, "post", new_callable=AsyncMock, return_value=mock_response
        ):
            results = await provider.embed_batch(["Hello", "World"])

        assert len(results) == 2
        assert len(results[0]) == 1536
        assert len(results[1]) == 1536

    async def test_embed_api_error_raises(self, provider: EmbeddingProvider):
        """Non-200 response raises RuntimeError."""
        mock_response = httpx.Response(500, text="Internal Server Error")

        with patch.object(
            provider._client, "post", new_callable=AsyncMock, return_value=mock_response
        ):
            with pytest.raises(RuntimeError, match="Embedding API error"):
                await provider.embed("fail")
