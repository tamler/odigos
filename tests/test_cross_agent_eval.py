"""Tests for cross-agent evaluation routing."""
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

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
    return provider


@pytest.mark.asyncio
async def test_find_qualified_evaluator(db, mock_provider):
    """Should find a qualified peer evaluator for a task type."""
    evaluator = Evaluator(db=db, provider=mock_provider)

    # Register a qualified peer
    await db.execute(
        "INSERT INTO agent_registry (agent_name, role, specialty, status, "
        "evolution_score, allow_external_evaluation) VALUES (?, ?, ?, ?, ?, ?)",
        ("CodeBot", "backend_dev", "coding", "online", 8.0, 1),
    )

    result = await evaluator.find_qualified_evaluator("coding")
    assert result is not None
    assert result["agent_name"] == "CodeBot"


@pytest.mark.asyncio
async def test_no_qualified_evaluator_offline(db, mock_provider):
    """Should not return offline peers."""
    evaluator = Evaluator(db=db, provider=mock_provider)

    await db.execute(
        "INSERT INTO agent_registry (agent_name, role, specialty, status, "
        "evolution_score, allow_external_evaluation) VALUES (?, ?, ?, ?, ?, ?)",
        ("CodeBot", "backend_dev", "coding", "offline", 8.0, 1),
    )

    result = await evaluator.find_qualified_evaluator("coding")
    assert result is None


@pytest.mark.asyncio
async def test_no_qualified_evaluator_low_score(db, mock_provider):
    """Should not return peers with low evolution score."""
    evaluator = Evaluator(db=db, provider=mock_provider)

    await db.execute(
        "INSERT INTO agent_registry (agent_name, role, specialty, status, "
        "evolution_score, allow_external_evaluation) VALUES (?, ?, ?, ?, ?, ?)",
        ("CodeBot", "backend_dev", "coding", "online", 5.0, 1),
    )

    result = await evaluator.find_qualified_evaluator("coding")
    assert result is None


@pytest.mark.asyncio
async def test_no_qualified_evaluator_not_opted_in(db, mock_provider):
    """Should not return peers that haven't opted in."""
    evaluator = Evaluator(db=db, provider=mock_provider)

    await db.execute(
        "INSERT INTO agent_registry (agent_name, role, specialty, status, "
        "evolution_score, allow_external_evaluation) VALUES (?, ?, ?, ?, ?, ?)",
        ("CodeBot", "backend_dev", "coding", "online", 8.0, 0),
    )

    result = await evaluator.find_qualified_evaluator("coding")
    assert result is None
