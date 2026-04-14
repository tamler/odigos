"""Tests for LLMClient.complete_json() and supports_explicit_cache."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from odigos.config import ModelConfig, ProviderConfig
from odigos.providers.base import LLMResponse
from odigos.providers.llm import LLMClient


def _make_client(model_id: str = "test-model", base_url: str = "http://localhost/v1") -> LLMClient:
    return LLMClient(
        providers={"p": ProviderConfig(base_url=base_url, api_key="fake")},
        models={
            "m": ModelConfig(provider="p", id=model_id),
        },
        routing={"fast": "m"},
    )


@pytest.mark.asyncio
async def test_complete_json_valid_json():
    client = _make_client()
    payload = {"entities": []}
    resp = LLMResponse(
        content=json.dumps(payload), model="test",
        tokens_in=10, tokens_out=5, cost_usd=0.0,
    )
    client.complete = AsyncMock(return_value=resp)

    result, ok = await client.complete_json([{"role": "user", "content": "test"}])
    assert ok is True
    assert result == {"entities": []}


@pytest.mark.asyncio
async def test_complete_json_tier3_regex():
    client = _make_client()
    call_count = 0

    async def mock_complete(messages, **kwargs):
        nonlocal call_count
        call_count += 1
        if "response_format" in kwargs:
            raise RuntimeError("Simulated format failure")
        return LLMResponse(
            content='Here is the result: ```json\n{"found": true}\n```',
            model="test", tokens_in=10, tokens_out=5, cost_usd=0.0,
        )

    client.complete = mock_complete
    result, ok = await client.complete_json([{"role": "user", "content": "test"}])
    assert ok is True
    assert result == {"found": True}
    assert call_count >= 2


@pytest.mark.asyncio
async def test_complete_json_all_fail():
    client = _make_client()

    async def mock_complete_fail(messages, **kwargs):
        if "response_format" in kwargs:
            raise RuntimeError("format not supported")
        return LLMResponse(
            content="no json here at all", model="test",
            tokens_in=10, tokens_out=5, cost_usd=0.0,
        )

    client.complete = mock_complete_fail
    result, ok = await client.complete_json([{"role": "user", "content": "test"}])
    assert ok is False
    assert result == {}


@pytest.mark.asyncio
async def test_complete_json_schema_validation_failure():
    client = _make_client()
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }

    async def mock_complete(messages, **kwargs):
        rf = kwargs.get("response_format", {})
        if rf.get("type") == "json_schema":
            raise RuntimeError("json_schema not supported")
        return LLMResponse(
            content='{"wrong_field": 123}', model="test",
            tokens_in=10, tokens_out=5, cost_usd=0.0,
        )

    client.complete = mock_complete
    result, ok = await client.complete_json(
        [{"role": "user", "content": "test"}], schema=schema
    )
    assert ok is False
    assert result == {}


def test_supports_explicit_cache_true():
    """Model name containing 'claude' returns True."""
    client = _make_client(model_id="anthropic/claude-3.5-sonnet")
    assert client.supports_explicit_cache is True


def test_supports_explicit_cache_true_by_url():
    """Provider base_url containing 'anthropic' returns True."""
    client = _make_client(model_id="some-model", base_url="https://api.anthropic.com/v1")
    assert client.supports_explicit_cache is True


def test_supports_explicit_cache_false():
    """Non-Anthropic model + non-Anthropic URL returns False."""
    client = _make_client(model_id="meta-llama/llama-4-scout")
    assert client.supports_explicit_cache is False
