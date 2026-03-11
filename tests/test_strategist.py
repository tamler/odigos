"""Tests for the Strategist module."""
import json
import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from odigos.core.strategist import Strategist
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


@pytest.fixture
def mock_evolution():
    ev = AsyncMock()
    ev.get_failed_trials = AsyncMock(return_value=[])
    ev.get_recent_directions = AsyncMock(return_value=[])
    ev.create_trial = AsyncMock(return_value="trial-123")
    ev.log_direction = AsyncMock(return_value="dir-123")
    return ev


@pytest.mark.asyncio
async def test_should_run_checks_evaluation_count(db, mock_provider, mock_evolution):
    strategist = Strategist(
        db=db, provider=mock_provider, evolution_engine=mock_evolution,
        agent_description="Test agent", agent_tools=["search", "code_execute"],
    )
    # No evaluations — should not run
    assert await strategist.should_run() is False

    # Add 10 evaluations
    for i in range(10):
        await db.execute(
            "INSERT INTO evaluations (id, overall_score, created_at) VALUES (?, ?, datetime('now'))",
            (str(uuid.uuid4()), 7.0),
        )
    assert await strategist.should_run() is True


@pytest.mark.asyncio
async def test_analyze_generates_hypotheses(db, mock_provider, mock_evolution):
    strategist = Strategist(
        db=db, provider=mock_provider, evolution_engine=mock_evolution,
        agent_description="Test agent", agent_tools=["search"],
    )
    # Seed evaluations
    for i in range(10):
        await db.execute(
            "INSERT INTO evaluations (id, task_type, overall_score, implicit_feedback, created_at) "
            "VALUES (?, ?, ?, ?, datetime('now'))",
            (str(uuid.uuid4()), "research", 5.0 + (i % 3), 0.2),
        )

    # Mock LLM returns hypotheses
    mock_provider.complete = AsyncMock(return_value=AsyncMock(content=json.dumps({
        "analysis": "Research tasks scoring below average",
        "direction": "Improve research thoroughness",
        "hypotheses": [
            {
                "type": "trial_hypothesis",
                "hypothesis": "Add more detail to research responses",
                "target": "prompt_section",
                "target_name": "voice",
                "change": "When researching, provide comprehensive summaries with sources.",
                "confidence": 0.8,
            }
        ],
        "specialization_proposals": [],
    })))

    result = await strategist.analyze()
    assert result is not None
    assert len(result["hypotheses"]) == 1
    assert result["hypotheses"][0]["confidence"] == 0.8

    # Verify strategist run was recorded
    run = await db.fetch_one("SELECT * FROM strategist_runs ORDER BY created_at DESC LIMIT 1")
    assert run is not None


@pytest.mark.asyncio
async def test_auto_creates_trial_above_threshold(db, mock_provider, mock_evolution):
    strategist = Strategist(
        db=db, provider=mock_provider, evolution_engine=mock_evolution,
        agent_description="Test agent", agent_tools=["search"],
    )
    # Seed evaluations
    for i in range(10):
        await db.execute(
            "INSERT INTO evaluations (id, task_type, overall_score, created_at) VALUES (?, ?, ?, datetime('now'))",
            (str(uuid.uuid4()), "general", 6.0),
        )

    mock_provider.complete = AsyncMock(return_value=AsyncMock(content=json.dumps({
        "analysis": "Responses could be more concise",
        "direction": "Improve conciseness",
        "hypotheses": [
            {
                "type": "trial_hypothesis",
                "hypothesis": "Be more concise",
                "target": "prompt_section",
                "target_name": "voice",
                "change": "Keep responses brief and direct.",
                "confidence": 0.8,
            }
        ],
        "specialization_proposals": [],
    })))

    result = await strategist.analyze()
    # Should auto-create trial since confidence > 0.7
    mock_evolution.create_trial.assert_called_once()


@pytest.mark.asyncio
async def test_specialization_proposal_stored(db, mock_provider, mock_evolution):
    strategist = Strategist(
        db=db, provider=mock_provider, evolution_engine=mock_evolution,
        agent_description="Test agent", agent_tools=["search"],
    )
    for i in range(10):
        await db.execute(
            "INSERT INTO evaluations (id, task_type, overall_score, created_at) VALUES (?, ?, ?, datetime('now'))",
            (str(uuid.uuid4()), "coding", 4.0),
        )

    mock_provider.complete = AsyncMock(return_value=AsyncMock(content=json.dumps({
        "analysis": "Coding tasks consistently low",
        "direction": "Consider delegation",
        "hypotheses": [],
        "specialization_proposals": [
            {
                "role": "backend_dev",
                "specialty": "coding",
                "description": "Python backend specialist",
                "rationale": "Coding scores consistently below 5.0",
            }
        ],
    })))

    await strategist.analyze()
    proposal = await db.fetch_one("SELECT * FROM specialization_proposals WHERE status = 'pending'")
    assert proposal is not None
    assert proposal["role"] == "backend_dev"
