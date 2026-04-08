"""Tests for odigos/memory/extractor.py"""
import json
from types import SimpleNamespace

import pytest

from odigos.memory.extractor import extract_knowledge


class FakeLLM:
    def __init__(self, response_content: str):
        self._content = response_content
        self.called = False

    async def complete(self, messages, **kwargs):
        self.called = True
        return SimpleNamespace(
            content=self._content,
            model="test",
            tokens_in=0,
            tokens_out=0,
            cost_usd=0,
        )

    async def complete_json(self, messages, **kwargs):
        resp = await self.complete(messages, **kwargs)
        try:
            import json
            parsed = json.loads(resp.content)
            return parsed, True
        except Exception:
            return {}, False


@pytest.mark.asyncio
async def test_extract_entities_and_facts():
    payload = {
        "entities": [{"name": "Alice", "type": "person", "summary": "A developer"}],
        "facts": [{"text": "Alice uses Python", "category": "knowledge", "about": "Alice"}],
        "relationships": [{"from": "Alice", "relationship": "works on", "to": "Odigos"}],
    }
    provider = FakeLLM(json.dumps(payload))
    result = await extract_knowledge(
        provider,
        user_message="Tell me about Alice, the developer who works on Odigos.",
        assistant_response="Alice is a developer who uses Python on the Odigos project.",
    )

    assert len(result["entities"]) == 1
    assert result["entities"][0]["name"] == "Alice"
    assert len(result["facts"]) == 1
    assert result["facts"][0]["text"] == "Alice uses Python"
    assert len(result["relationships"]) == 1
    assert result["relationships"][0]["relationship"] == "works on"


@pytest.mark.asyncio
async def test_extract_returns_empty_on_small_talk():
    provider = FakeLLM("{}")
    result = await extract_knowledge(
        provider,
        user_message="thanks",
        assistant_response="You're welcome!",
    )

    assert result == {"entities": [], "facts": [], "relationships": []}


@pytest.mark.asyncio
async def test_extract_returns_empty_on_short_message():
    provider = FakeLLM("{}")
    result = await extract_knowledge(
        provider,
        user_message="ok",
        assistant_response="Got it.",
    )

    assert result == {"entities": [], "facts": [], "relationships": []}
    assert not provider.called


@pytest.mark.asyncio
async def test_extract_handles_malformed_response():
    provider = FakeLLM("not valid json")
    result = await extract_knowledge(
        provider,
        user_message="What is the capital of France and its population?",
        assistant_response="Paris is the capital of France, with a population of about 2 million.",
    )

    assert result == {"entities": [], "facts": [], "relationships": []}
