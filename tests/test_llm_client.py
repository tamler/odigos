"""Tests for LLMClient — the core LLM calling path."""

from unittest.mock import AsyncMock, patch, MagicMock
import pytest

from odigos.providers.llm import LLMClient, LLMResponse


@pytest.fixture
def client():
    return LLMClient(
        api_key="test-key",
        base_url="https://fake.api/v1",
        default_model="default-model",
        fallback_model="fallback-model",
    )


class TestCompleteWithModelKwarg:
    """Router passes model= as a kwarg. Must not cause 'multiple values' error."""

    @pytest.mark.asyncio
    async def test_model_kwarg_does_not_duplicate(self, client):
        """Regression: router calls complete(messages, model='x').

        complete() must pop 'model' from kwargs before passing to _call(),
        otherwise _call() gets model as both positional and keyword arg.
        """
        fake_response = LLMResponse(
            content="hello",
            model="routed-model",
            tokens_in=5, tokens_out=3, cost_usd=0.0,
        )
        with patch.object(client, "_call", new_callable=AsyncMock, return_value=fake_response) as mock_call:
            result = await client.complete(
                [{"role": "user", "content": "hi"}],
                model="routed-model",
            )

            assert result.content == "hello"
            # _call should receive model as positional arg, NOT in kwargs
            mock_call.assert_awaited_once()
            args, kwargs = mock_call.call_args
            assert args[1] == "routed-model"  # positional model arg
            assert "model" not in kwargs  # must not be in kwargs too

    @pytest.mark.asyncio
    async def test_default_model_used_when_no_kwarg(self, client):
        """When no model kwarg, uses default_model."""
        fake_response = LLMResponse(
            content="hello",
            model="default-model",
            tokens_in=5, tokens_out=3, cost_usd=0.0,
        )
        with patch.object(client, "_call", new_callable=AsyncMock, return_value=fake_response) as mock_call:
            await client.complete([{"role": "user", "content": "hi"}])

            args, kwargs = mock_call.call_args
            assert args[1] == "default-model"
            assert "model" not in kwargs

    @pytest.mark.asyncio
    async def test_fallback_on_first_model_failure(self, client):
        """Falls back to fallback_model when primary fails."""
        fake_response = LLMResponse(
            content="from fallback",
            model="fallback-model",
            tokens_in=5, tokens_out=3, cost_usd=0.0,
        )
        with patch.object(
            client, "_call",
            new_callable=AsyncMock,
            side_effect=[RuntimeError("rate limited"), fake_response],
        ) as mock_call:
            result = await client.complete(
                [{"role": "user", "content": "hi"}],
                model="primary-model",
            )

            assert result.content == "from fallback"
            assert mock_call.await_count == 2
            # First call with primary, second with fallback
            assert mock_call.call_args_list[0][0][1] == "primary-model"
            assert mock_call.call_args_list[1][0][1] == "fallback-model"
