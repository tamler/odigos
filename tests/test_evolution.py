"""Tests for the EvolutionEngine."""
import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from odigos.core.evolution import EvolutionEngine
from odigos.db import Database


@pytest_asyncio.fixture
async def db():
    d = Database(":memory:", migrations_dir="migrations")
    await d.initialize()
    # Create a checkpoint row so FK references from trials work
    await d.execute(
        "INSERT INTO checkpoints (id, label) VALUES (?, ?)",
        ("cp-123", "test-checkpoint"),
    )
    yield d
    await d.close()


@pytest.fixture
def mock_checkpoint():
    mgr = AsyncMock()
    mgr.create_checkpoint = AsyncMock(return_value="cp-123")
    mgr.get_active_trial = AsyncMock(return_value=None)
    mgr.promote_trial = AsyncMock(return_value="cp-456")
    mgr.revert_trial = AsyncMock()
    mgr.expire_stale_trials = AsyncMock(return_value=0)
    return mgr


@pytest.fixture
def mock_evaluator():
    ev = AsyncMock()
    ev.get_unscored_messages = AsyncMock(return_value=[])
    ev.evaluate_action = AsyncMock(return_value={
        "eval_id": "eval-1",
        "task_type": "general",
        "overall_score": 7.0,
        "implicit_feedback": 0.3,
        "improvement_signal": None,
    })
    return ev


@pytest.fixture
def mock_provider():
    provider = AsyncMock()
    provider.fallback_model = "test-fallback"
    response = AsyncMock()
    response.content = "Lesson: the change was too aggressive."
    provider.complete = AsyncMock(return_value=response)
    return provider


@pytest.mark.asyncio
async def test_create_trial(db, mock_checkpoint, mock_evaluator, mock_provider):
    engine = EvolutionEngine(
        db=db, checkpoint_manager=mock_checkpoint,
        evaluator=mock_evaluator, provider=mock_provider,
    )
    trial_id = await engine.create_trial(
        hypothesis="Be more concise in coding responses",
        target="prompt_section",
        change_description="Shortened voice section",
        overrides={"voice": "Be extremely concise. No fluff."},
    )
    assert trial_id is not None
    trial = await db.fetch_one("SELECT * FROM trials WHERE id = ?", (trial_id,))
    assert trial["status"] == "active"
    assert trial["hypothesis"] == "Be more concise in coding responses"
    override = await db.fetch_one(
        "SELECT * FROM trial_overrides WHERE trial_id = ?", (trial_id,)
    )
    assert override["target_name"] == "voice"


@pytest.mark.asyncio
async def test_check_trial_promotes_when_better(db, mock_checkpoint, mock_evaluator, mock_provider):
    engine = EvolutionEngine(
        db=db, checkpoint_manager=mock_checkpoint,
        evaluator=mock_evaluator, provider=mock_provider,
    )
    trial_id = await engine.create_trial(
        hypothesis="test", target="prompt_section",
        change_description="test change",
        overrides={"voice": "new voice"},
    )
    # Simulate evaluations showing improvement
    await db.execute(
        "UPDATE trials SET evaluation_count = 6, avg_score = 8.5, "
        "baseline_avg_score = 7.0 WHERE id = ?",
        (trial_id,),
    )
    mock_checkpoint.get_active_trial = AsyncMock(return_value=dict(
        await db.fetch_one("SELECT * FROM trials WHERE id = ?", (trial_id,))
    ))
    await engine.check_active_trial()
    mock_checkpoint.promote_trial.assert_called_once_with(trial_id)


@pytest.mark.asyncio
async def test_check_trial_reverts_when_worse(db, mock_checkpoint, mock_evaluator, mock_provider):
    engine = EvolutionEngine(
        db=db, checkpoint_manager=mock_checkpoint,
        evaluator=mock_evaluator, provider=mock_provider,
    )
    trial_id = await engine.create_trial(
        hypothesis="test", target="prompt_section",
        change_description="bad change",
        overrides={"voice": "bad voice"},
    )
    await db.execute(
        "UPDATE trials SET evaluation_count = 6, avg_score = 5.0, "
        "baseline_avg_score = 7.0 WHERE id = ?",
        (trial_id,),
    )
    mock_checkpoint.get_active_trial = AsyncMock(return_value=dict(
        await db.fetch_one("SELECT * FROM trials WHERE id = ?", (trial_id,))
    ))
    await engine.check_active_trial()
    mock_checkpoint.revert_trial.assert_called_once()
    row = await db.fetch_one("SELECT * FROM failed_trials_log WHERE trial_id = ?", (trial_id,))
    assert row is not None
    assert row["failure_reason"] == "worse_than_baseline"


@pytest.mark.asyncio
async def test_log_direction(db, mock_checkpoint, mock_evaluator, mock_provider):
    engine = EvolutionEngine(
        db=db, checkpoint_manager=mock_checkpoint,
        evaluator=mock_evaluator, provider=mock_provider,
    )
    await engine.log_direction(
        analysis="Scoring well on code tasks, weak on research",
        direction="Focus on improving research depth",
        opportunities=[{"area": "research", "potential": "high"}],
        hypotheses=[],
        confidence=0.7,
        based_on_evaluations=25,
    )
    row = await db.fetch_one("SELECT * FROM direction_log ORDER BY created_at DESC LIMIT 1")
    assert row is not None
    assert "research" in row["direction"]


@pytest.mark.asyncio
async def test_get_failed_trials(db, mock_checkpoint, mock_evaluator, mock_provider):
    engine = EvolutionEngine(
        db=db, checkpoint_manager=mock_checkpoint,
        evaluator=mock_evaluator, provider=mock_provider,
    )
    # Create a real trial row so the FK on failed_trials_log is satisfied
    await db.execute(
        "INSERT INTO trials (id, checkpoint_id, hypothesis, target, expires_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("t-1", "cp-123", "be concise", "prompt_section", "2099-01-01T00:00:00"),
    )
    await db.execute(
        "INSERT INTO failed_trials_log (id, trial_id, hypothesis, target, failure_reason, lessons) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), "t-1", "be concise", "prompt_section", "worse_than_baseline",
         "Users prefer detailed responses for technical topics"),
    )
    failed = await engine.get_failed_trials(limit=10)
    assert len(failed) == 1
    assert failed[0]["hypothesis"] == "be concise"
