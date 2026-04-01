"""Tests for the knowledge lookup tool."""
import asyncio

import pytest

from odigos.tools.knowledge import LookupTool


@pytest.fixture
def tool():
    return LookupTool()


def test_tool_metadata(tool):
    assert tool.name == "lookup_fact"
    props = tool.parameters_schema["properties"]
    assert "query" in props
    assert "source" in props
    assert props["source"]["enum"] == [
        "auto",
        "grokipedia",
        "wikipedia",
    ]
    assert tool.parameters_schema["required"] == ["query"]


def test_empty_query(tool):
    result = asyncio.get_event_loop().run_until_complete(
        tool.execute({"query": ""})
    )
    assert not result.success
    assert result.error == "No query provided"


def test_empty_query_missing(tool):
    result = asyncio.get_event_loop().run_until_complete(
        tool.execute({})
    )
    assert not result.success
    assert result.error == "No query provided"


@pytest.mark.network
@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("wikipedia"),
    reason="wikipedia not installed",
)
def test_lookup_auto(tool):
    result = asyncio.get_event_loop().run_until_complete(
        tool.execute({"query": "Python programming language"})
    )
    assert result.success
    assert result.data
    assert "Python" in result.data


@pytest.mark.network
@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("wikipedia"),
    reason="wikipedia not installed",
)
def test_lookup_wikipedia_explicit(tool):
    result = asyncio.get_event_loop().run_until_complete(
        tool.execute({
            "query": "Python programming language",
            "source": "wikipedia",
        })
    )
    assert result.success
    assert "Wikipedia" in result.data
    assert "Python" in result.data


@pytest.mark.network
def test_lookup_grokipedia_explicit(tool):
    try:
        result = asyncio.get_event_loop().run_until_complete(
            tool.execute({
                "query": "Python programming language",
                "source": "grokipedia",
            })
        )
    except Exception:
        pytest.skip("Grokipedia API unavailable")
    if not result.success:
        pytest.skip("Grokipedia API returned no results")
    assert "Grokipedia" in result.data
    assert "Python" in result.data
