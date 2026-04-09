"""Tests for memory content classifier."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from odigos.memory.classifier import MemoryClassifier, ClassificationResult
from odigos.providers.base import LLMResponse


def _make_llm_response(content: str) -> LLMResponse:
    return LLMResponse(
        content=content, model="test/model",
        tokens_in=50, tokens_out=100, cost_usd=0.001,
    )


class TestClassifier:
    async def test_classifies_preference(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=_make_llm_response(json.dumps({
            "memory_type": "preference",
            "keywords": ["scheduling", "morning"],
            "tags": ["user-profile"],
            "context_description": "User dislikes early morning meetings.",
        })))
        classifier = MemoryClassifier(llm_client=mock_llm, prompts_dir="data/prompts")
        result = await classifier.classify("Don't schedule meetings before 10am")
        assert result.memory_type == "preference"
        assert "scheduling" in result.keywords
        assert result.context_description is not None

    async def test_classifies_entity(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=_make_llm_response(json.dumps({
            "memory_type": "entity",
            "keywords": ["Rachel", "tester", "Kimi K2"],
            "tags": ["team"],
            "context_description": "Rachel is a tester who uses Kimi K2.",
        })))
        classifier = MemoryClassifier(llm_client=mock_llm, prompts_dir="data/prompts")
        result = await classifier.classify("Rachel is a tester, she uses Kimi K2")
        assert result.memory_type == "entity"
        assert "Rachel" in result.keywords

    async def test_fallback_on_parse_failure(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=_make_llm_response("not valid json"))
        classifier = MemoryClassifier(llm_client=mock_llm, prompts_dir="data/prompts")
        result = await classifier.classify("Some random content")
        assert result.memory_type == "general"
        assert result.context_description == "Some random content"

    async def test_bulk_classify_returns_shared_metadata(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=_make_llm_response(json.dumps({
            "memory_type": "general",
            "keywords": ["deployment", "docker"],
            "tags": ["infrastructure"],
            "context_description": "Document about Docker deployment.",
        })))
        classifier = MemoryClassifier(llm_client=mock_llm, prompts_dir="data/prompts")
        result = await classifier.classify_document(
            filename="deploy-guide.md",
            first_chunk="This guide covers Docker deployment...",
        )
        assert result.memory_type == "general"
        assert "docker" in [k.lower() for k in result.keywords]
        assert mock_llm.complete.call_count == 1
