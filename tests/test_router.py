import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock

import pytest

from odigos.core.router import ModelRouter
from odigos.providers.base import LLMResponse


def _make_response(model: str = "model-a") -> LLMResponse:
    return LLMResponse(
        content="ok",
        model=model,
        tokens_in=10,
        tokens_out=5,
        cost_usd=0.0,
    )


class TestModelRouter:
    @pytest.fixture
    def mock_provider(self):
        provider = AsyncMock()
        provider.complete.return_value = _make_response("model-a:free")
        return provider

    async def test_routes_to_free_pool(self, mock_provider):
        """Router passes a model from the free pool to the provider."""
        router = ModelRouter(
            provider=mock_provider,
            free_pool=["model-a:free", "model-b:free"],
            rate_limit_rpm=20,
        )
        result = await router.complete([{"role": "user", "content": "hi"}])

        assert result.content == "ok"
        call_kwargs = mock_provider.complete.call_args
        assert call_kwargs.kwargs.get("model") in ["model-a:free", "model-b:free"]

    async def test_round_robins(self, mock_provider):
        """Router cycles through models."""
        router = ModelRouter(
            provider=mock_provider,
            free_pool=["model-a:free", "model-b:free"],
            rate_limit_rpm=20,
        )
        models_used = []
        for _ in range(4):
            await router.complete([{"role": "user", "content": "hi"}])
            model = mock_provider.complete.call_args.kwargs.get("model")
            models_used.append(model)

        assert "model-a:free" in models_used
        assert "model-b:free" in models_used

    async def test_rotates_on_rate_limit(self, mock_provider):
        """Router tries next model when current model returns 429."""
        call_count = 0

        async def side_effect(messages, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("OpenRouter API error 429: Rate limited")
            return _make_response(kwargs.get("model", "model-b:free"))

        mock_provider.complete.side_effect = side_effect

        router = ModelRouter(
            provider=mock_provider,
            free_pool=["model-a:free", "model-b:free"],
            rate_limit_rpm=20,
        )
        result = await router.complete([{"role": "user", "content": "hi"}])

        assert result.content == "ok"
        assert mock_provider.complete.call_count == 2

    async def test_all_exhausted_raises(self, mock_provider):
        """Router raises when all models are exhausted."""
        mock_provider.complete.side_effect = RuntimeError("429: Rate limited")

        router = ModelRouter(
            provider=mock_provider,
            free_pool=["model-a:free"],
            rate_limit_rpm=20,
        )
        with pytest.raises(RuntimeError, match="All models exhausted"):
            await router.complete([{"role": "user", "content": "hi"}])

    async def test_passes_complexity_through(self, mock_provider):
        """Router accepts complexity kwarg without error."""
        router = ModelRouter(
            provider=mock_provider,
            free_pool=["model-a:free"],
            rate_limit_rpm=20,
        )
        result = await router.complete(
            [{"role": "user", "content": "hi"}],
            complexity="light",
        )
        assert result.content == "ok"

    async def test_implements_llm_provider(self):
        """ModelRouter is a subclass of LLMProvider."""
        from odigos.providers.base import LLMProvider
        assert issubclass(ModelRouter, LLMProvider)

    async def test_close_delegates(self, mock_provider):
        """Router close delegates to underlying provider."""
        router = ModelRouter(
            provider=mock_provider,
            free_pool=["model-a:free"],
            rate_limit_rpm=20,
        )
        await router.close()
        mock_provider.close.assert_called_once()
