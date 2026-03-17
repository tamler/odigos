"""Tests for the DecomposeQueryTool."""
from __future__ import annotations

import json

import pytest

from odigos.tools.decompose import DecomposeQueryTool, format_steps
from odigos.providers.base import LLMResponse


class FakeProvider:
    """Minimal provider that returns a canned response."""

    def __init__(self, content: str, should_fail: bool = False) -> None:
        self._content = content
        self._should_fail = should_fail

    async def complete(self, messages: list[dict], **kwargs) -> LLMResponse:
        if self._should_fail:
            raise RuntimeError("LLM unavailable")
        return LLMResponse(
            content=self._content,
            model="test",
            tokens_in=10,
            tokens_out=20,
            cost_usd=0.0,
        )


def test_tool_metadata():
    tool = DecomposeQueryTool(provider=None)
    assert tool.name == "decompose_query"
    assert "sub-tasks" in tool.description
    props = tool.parameters_schema["properties"]
    assert "query" in props
    assert tool.parameters_schema["required"] == ["query"]


@pytest.mark.asyncio
async def test_decompose_formats_response():
    steps = [
        {"step": 1, "task": "Search for relevant documents", "approach": "Use document search"},
        {"step": 2, "task": "Extract key metrics", "approach": "Use code tool"},
        {"step": 3, "task": "Compare results", "approach": "Analyze and summarize"},
    ]
    provider = FakeProvider(content=json.dumps(steps))
    tool = DecomposeQueryTool(provider=provider)

    result = await tool.execute({"query": "Compare revenue across all quarterly reports"})

    assert result.success is True
    assert "1. Search for relevant documents" in result.data
    assert "2. Extract key metrics" in result.data
    assert "3. Compare results" in result.data
    assert "Approach: Use document search" in result.data
    assert "Approach: Use code tool" in result.data


@pytest.mark.asyncio
async def test_decompose_fallback_on_no_provider():
    tool = DecomposeQueryTool(provider=None)

    result = await tool.execute({"query": "Analyze all documents"})

    assert result.success is True
    assert "1. Analyze all documents" in result.data
    assert "Approach: Address directly" in result.data


@pytest.mark.asyncio
async def test_decompose_fallback_on_failure():
    provider = FakeProvider(content="", should_fail=True)
    tool = DecomposeQueryTool(provider=provider)

    result = await tool.execute({"query": "Multi-step research task"})

    assert result.success is True
    assert "1. Multi-step research task" in result.data
    assert "Approach: Address directly" in result.data


@pytest.mark.asyncio
async def test_decompose_fallback_on_invalid_json():
    provider = FakeProvider(content="not valid json at all")
    tool = DecomposeQueryTool(provider=provider)

    result = await tool.execute({"query": "Do something complex"})

    assert result.success is True
    assert "1. Do something complex" in result.data


@pytest.mark.asyncio
async def test_decompose_fallback_on_empty_array():
    provider = FakeProvider(content="[]")
    tool = DecomposeQueryTool(provider=provider)

    result = await tool.execute({"query": "Empty result case"})

    assert result.success is True
    assert "1. Empty result case" in result.data


@pytest.mark.asyncio
async def test_decompose_empty_query():
    tool = DecomposeQueryTool(provider=None)

    result = await tool.execute({"query": ""})

    assert result.success is False
    assert result.error == "No query provided"


@pytest.mark.asyncio
async def test_decompose_missing_query():
    tool = DecomposeQueryTool(provider=None)

    result = await tool.execute({})

    assert result.success is False
    assert result.error == "No query provided"


def test_format_steps_utility():
    steps = [
        {"step": 1, "task": "First task", "approach": "Method A"},
        {"step": 2, "task": "Second task", "approach": ""},
    ]
    output = format_steps(steps)
    assert "1. First task" in output
    assert "Approach: Method A" in output
    assert "2. Second task" in output
    # Empty approach should not produce an "Approach:" line
    lines = output.split("\n")
    assert not any("Approach: " in line and "Second" in lines[lines.index(line) - 1] for line in lines if "Approach" in line and line.strip() == "Approach: ")
