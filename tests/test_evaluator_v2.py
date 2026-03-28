"""Tests for evaluator v2: tool output evaluation + sprint contracts."""
import json
import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from odigos.core.evaluator import Evaluator
from odigos.db import Database


@pytest_asyncio.fixture
async def db():
    d = Database(":memory:", migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


@pytest.fixture
def mock_provider():
    provider = AsyncMock()
    provider.fallback_model = "test-fallback"
    provider.background_model = None
    return provider


@pytest.fixture
def evaluator(db, mock_provider):
    return Evaluator(db=db, provider=mock_provider)


# -- evaluate_tool_output tests --

@pytest.mark.asyncio
async def test_evaluate_tool_output_search(evaluator):
    """Search result with matching keywords scores high."""
    result = await evaluator.evaluate_tool_output(
        tool_name="web_search",
        tool_params={"query": "python decorators"},
        tool_result=(
            "Python decorators are a powerful feature that "
            "allows you to modify the behavior of functions. "
            "Decorators wrap a function to extend its behavior "
            "without permanently modifying it."
        ),
        user_query="explain python decorators",
    )
    assert result["quality"] >= 6
    assert result["relevant"] is True
    assert result["complete"] is True
    assert result["issues"] is None

    # Check it was persisted
    row = await evaluator.db.fetch_one(
        "SELECT * FROM tool_evaluations "
        "WHERE tool_name = 'web_search'"
    )
    assert row is not None
    assert row["quality_score"] >= 6


@pytest.mark.asyncio
async def test_evaluate_tool_output_error(evaluator):
    """Tool result with traceback scores low."""
    result = await evaluator.evaluate_tool_output(
        tool_name="run_code",
        tool_params={"code": "1/0"},
        tool_result=(
            "Traceback (most recent call last):\n"
            "  File \"<stdin>\", line 1\n"
            "ZeroDivisionError: division by zero"
        ),
        user_query="divide one by zero",
    )
    assert result["quality"] <= 3
    assert result["complete"] is False
    assert "error" in (result["issues"] or "").lower()


@pytest.mark.asyncio
async def test_evaluate_tool_output_empty(evaluator):
    """Empty result scores low."""
    result = await evaluator.evaluate_tool_output(
        tool_name="web_search",
        tool_params={"query": "obscure topic"},
        tool_result="",
        user_query="find info about obscure topic",
    )
    assert result["quality"] <= 2
    assert result["complete"] is False
    assert result["relevant"] is False


# -- sprint contract tests --

@pytest.mark.asyncio
async def test_sprint_contract_format(evaluator, mock_provider):
    """Verify contract structure from LLM response."""
    mock_provider.complete = AsyncMock(
        return_value=AsyncMock(
            content=json.dumps({
                "criteria": [
                    {
                        "step": 1,
                        "test": "Search returns results",
                        "metric": "at least 3 results",
                    },
                    {
                        "step": 2,
                        "test": "Summary is generated",
                        "metric": "200+ words",
                    },
                ],
                "overall_success": (
                    "User receives a comprehensive summary"
                ),
            })
        )
    )

    contract = await evaluator.generate_sprint_contract(
        goal="Research and summarize topic",
        steps=[
            {"step": 1, "task": "Search for information"},
            {"step": 2, "task": "Summarize findings"},
        ],
    )

    assert "criteria" in contract
    assert isinstance(contract["criteria"], list)
    assert len(contract["criteria"]) == 2
    assert "overall_success" in contract
    for c in contract["criteria"]:
        assert "step" in c
        assert "test" in c
        assert "metric" in c


@pytest.mark.asyncio
async def test_sprint_contract_fallback(evaluator, mock_provider):
    """When LLM fails, returns empty contract."""
    mock_provider.complete = AsyncMock(
        side_effect=RuntimeError("LLM down")
    )

    contract = await evaluator.generate_sprint_contract(
        goal="Do something",
        steps=[{"step": 1, "task": "Step one"}],
    )

    assert contract["criteria"] == []
    assert contract["overall_success"] == "unknown"


@pytest.mark.asyncio
async def test_evaluate_search_no_results(evaluator):
    """Search with 'no results' message scores low."""
    result = await evaluator.evaluate_tool_output(
        tool_name="web_search",
        tool_params={"query": "xyz"},
        tool_result="No results found for your query.",
        user_query="search for xyz",
    )
    assert result["quality"] <= 3
    assert result["complete"] is False


@pytest.mark.asyncio
async def test_evaluate_file_creation(evaluator):
    """File creation tool with confirmation scores well."""
    result = await evaluator.evaluate_tool_output(
        tool_name="create_file",
        tool_params={"path": "/tmp/test.txt"},
        tool_result="File created at /tmp/test.txt",
        user_query="create a test file",
    )
    assert result["quality"] >= 6
    assert result["relevant"] is True
