from unittest.mock import AsyncMock, patch

import httpx
import pytest

from odigos.providers.base import LLMResponse
from odigos.providers.openrouter import OpenRouterProvider


@pytest.fixture
def provider() -> OpenRouterProvider:
    return OpenRouterProvider(
        api_key="test-key",
        default_model="test/model",
        fallback_model="test/fallback",
        max_tokens=100,
        temperature=0.5,
    )


def _mock_response(content: str = "Hello!", model: str = "test/model") -> dict:
    return {
        "choices": [{"message": {"content": content}}],
        "model": model,
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


async def test_complete_success(provider: OpenRouterProvider):
    """Successful completion returns LLMResponse."""
    mock_resp = httpx.Response(200, json=_mock_response())

    with patch.object(provider._client, "post", new_callable=AsyncMock, return_value=mock_resp):
        result = await provider.complete([{"role": "user", "content": "Hi"}])

    assert isinstance(result, LLMResponse)
    assert result.content == "Hello!"
    assert result.model == "test/model"
    assert result.tokens_in == 10
    assert result.tokens_out == 5


async def test_complete_falls_back_on_error(provider: OpenRouterProvider):
    """Falls back to fallback model on primary model failure."""
    error_resp = httpx.Response(500, json={"error": "internal"})
    success_resp = httpx.Response(200, json=_mock_response("Fallback!", "test/fallback"))

    call_count = 0

    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return error_resp
        return success_resp

    with patch.object(provider._client, "post", side_effect=mock_post):
        result = await provider.complete([{"role": "user", "content": "Hi"}])

    assert result.content == "Fallback!"
    assert result.model == "test/fallback"


async def test_complete_raises_on_total_failure(provider: OpenRouterProvider):
    """Raises when both primary and fallback fail."""
    error_resp = httpx.Response(500, json={"error": "internal"})

    with patch.object(provider._client, "post", new_callable=AsyncMock, return_value=error_resp):
        with pytest.raises(RuntimeError, match="All LLM providers failed"):
            await provider.complete([{"role": "user", "content": "Hi"}])
