"""Tests for LLMClient — multi-provider, tiered routing, fallback dispatch."""

from unittest.mock import AsyncMock, patch
import pytest

from odigos.providers.llm import LLMClient, LLMResponse
from odigos.config import ProviderConfig, ModelConfig


@pytest.fixture
def client():
    providers = {
        "openrouter": ProviderConfig(base_url="https://fake.api/v1", api_key="test-key"),
    }
    models = {
        "default": ModelConfig(provider="openrouter", id="default-model"),
        "fallback": ModelConfig(provider="openrouter", id="fallback-model"),
        "smart-model": ModelConfig(provider="openrouter", id="smart-model-id"),
    }
    routing = {
        "fast": "default",
        "smart": "smart-model",
        "background": "default",
        "fallback": "fallback",
    }
    return LLMClient(providers=providers, models=models, routing=routing)


class TestCompleteWithModelKwarg:
    """Callers can still pass literal `model=` and get it routed correctly."""

    @pytest.mark.asyncio
    async def test_literal_model_kwarg_dispatches_correctly(self, client):
        fake_response = LLMResponse(
            content="hello",
            model="default-model",
            tokens_in=5, tokens_out=3, cost_usd=0.0,
        )
        with patch.object(
            client, "_call", new_callable=AsyncMock, return_value=fake_response,
        ) as mock_call:
            result = await client.complete(
                [{"role": "user", "content": "hi"}],
                model="default-model",
            )
            assert result.content == "hello"
            mock_call.assert_awaited_once()
            # _call receives the ModelConfig as positional arg
            args, kwargs = mock_call.call_args
            assert args[1].id == "default-model"
            assert "model" not in kwargs

    @pytest.mark.asyncio
    async def test_default_intelligence_fast(self, client):
        fake_response = LLMResponse(
            content="hello", model="default-model",
            tokens_in=5, tokens_out=3, cost_usd=0.0,
        )
        with patch.object(
            client, "_call", new_callable=AsyncMock, return_value=fake_response,
        ) as mock_call:
            await client.complete([{"role": "user", "content": "hi"}])
            args, _ = mock_call.call_args
            # fast tier → "default" alias → "default-model" id
            assert args[1].id == "default-model"

    @pytest.mark.asyncio
    async def test_smart_tier_selects_smart_model(self, client):
        fake_response = LLMResponse(
            content="x", model="smart-model-id",
            tokens_in=5, tokens_out=3, cost_usd=0.0,
        )
        with patch.object(
            client, "_call", new_callable=AsyncMock, return_value=fake_response,
        ) as mock_call:
            await client.complete(
                [{"role": "user", "content": "hi"}],
                intelligence="smart",
            )
            args, _ = mock_call.call_args
            assert args[1].id == "smart-model-id"

    @pytest.mark.asyncio
    async def test_fallback_on_first_model_failure(self, client):
        fake_response = LLMResponse(
            content="from fallback", model="fallback-model",
            tokens_in=5, tokens_out=3, cost_usd=0.0,
        )
        with patch.object(
            client, "_call", new_callable=AsyncMock,
            side_effect=[RuntimeError("rate limited"), fake_response],
        ) as mock_call:
            result = await client.complete([{"role": "user", "content": "hi"}])
            assert result.content == "from fallback"
            assert mock_call.await_count == 2
            assert mock_call.call_args_list[0][0][1].id == "default-model"
            assert mock_call.call_args_list[1][0][1].id == "fallback-model"

    def test_resolve_properties(self, client):
        assert client.default_model == "default-model"
        assert client.fallback_model == "fallback-model"
        assert client.resolve("smart").id == "smart-model-id"
        assert client.resolve("background").id == "default-model"
