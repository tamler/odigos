"""Tests for LLMClient.complete_json() and supports_explicit_cache."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from odigos.providers.base import LLMResponse
from odigos.providers.llm import LLMClient


class FakeLLMClient(LLMClient):
    """LLMClient with _call overridden to return preset responses."""

    def __init__(self, default_model: str = "test-model", base_url: str = "http://localhost"):
        self.base_url = base_url
        self.api_key = "fake"
        self.default_model = default_model
        self.fallback_model = default_model
        self.max_tokens = 100
        self.temperature = 0.0
        self._cost_per_million = 0.0
        self._client = None  # not used in tests

    async def _call(self, messages, model, **kwargs):
        raise NotImplementedError("Override complete() in tests")


@pytest.mark.asyncio
async def test_complete_json_valid_json():
    """Tier 1/2: valid JSON response returns (dict, True)."""
    client = FakeLLMClient()
    payload = {"entities": []}
    resp = LLMResponse(
        content=json.dumps(payload),
        model="test",
        tokens_in=10,
        tokens_out=5,
        cost_usd=0.0,
    )
    client.complete = AsyncMock(return_value=resp)

    result, ok = await client.complete_json([{"role": "user", "content": "test"}])
    assert ok is True
    assert result == {"entities": []}


@pytest.mark.asyncio
async def test_complete_json_tier3_regex():
    """Tier 3: regex extraction from freeform text with embedded JSON."""
    client = FakeLLMClient()

    call_count = 0

    async def mock_complete(messages, **kwargs):
        nonlocal call_count
        call_count += 1
        if "response_format" in kwargs:
            raise RuntimeError("Simulated format failure")
        return LLMResponse(
            content='Here is the result: ```json\n{"found": true}\n```',
            model="test",
            tokens_in=10,
            tokens_out=5,
            cost_usd=0.0,
        )

    client.complete = mock_complete

    result, ok = await client.complete_json([{"role": "user", "content": "test"}])
    assert ok is True
    assert result == {"found": True}
    # Should have called complete at least twice (tier 2 fails, tier 3 succeeds)
    assert call_count >= 2


@pytest.mark.asyncio
async def test_complete_json_all_fail():
    """All tiers fail: returns ({}, False)."""
    client = FakeLLMClient()

    async def mock_complete(messages, **kwargs):
        return LLMResponse(
            content="no json here at all",
            model="test",
            tokens_in=10,
            tokens_out=5,
            cost_usd=0.0,
        )

    client.complete = mock_complete

    # Tier 1 skipped (no schema), tier 2 will fail to parse "no json here",
    # tier 3 parse_json_response returns None for plain text
    # But tier 2 tries json_object format - mock returns non-JSON content
    # which will raise on json.loads, falling through to tier 3
    # tier 3 gets same non-JSON, parse_json_response returns None
    # We need complete to raise on response_format calls to test tier 3
    call_count = 0

    async def mock_complete_fail(messages, **kwargs):
        nonlocal call_count
        call_count += 1
        if "response_format" in kwargs:
            raise RuntimeError("format not supported")
        return LLMResponse(
            content="no json here at all",
            model="test",
            tokens_in=10,
            tokens_out=5,
            cost_usd=0.0,
        )

    client.complete = mock_complete_fail

    result, ok = await client.complete_json([{"role": "user", "content": "test"}])
    assert ok is False
    assert result == {}


@pytest.mark.asyncio
async def test_complete_json_schema_validation_failure():
    """Tier 2 returns valid JSON but fails schema validation."""
    client = FakeLLMClient()

    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }

    call_count = 0

    async def mock_complete(messages, **kwargs):
        nonlocal call_count
        call_count += 1
        rf = kwargs.get("response_format", {})
        if rf.get("type") == "json_schema":
            raise RuntimeError("json_schema not supported")
        return LLMResponse(
            content='{"wrong_field": 123}',
            model="test",
            tokens_in=10,
            tokens_out=5,
            cost_usd=0.0,
        )

    client.complete = mock_complete

    result, ok = await client.complete_json(
        [{"role": "user", "content": "test"}], schema=schema
    )
    assert ok is False
    assert result == {}


def test_supports_explicit_cache_true():
    """Model containing 'claude' returns True."""
    client = FakeLLMClient(default_model="anthropic/claude-3.5-sonnet")
    assert client.supports_explicit_cache is True


def test_supports_explicit_cache_true_by_url():
    """URL containing 'anthropic' returns True."""
    client = FakeLLMClient(default_model="some-model", base_url="https://api.anthropic.com")
    assert client.supports_explicit_cache is True


def test_supports_explicit_cache_false():
    """Non-Anthropic model returns False."""
    client = FakeLLMClient(default_model="meta-llama/llama-3-70b")
    assert client.supports_explicit_cache is False
