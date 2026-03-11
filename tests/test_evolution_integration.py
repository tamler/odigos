"""Integration test: full evolution cycle."""
import json
import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from odigos.core.checkpoint import CheckpointManager
from odigos.core.evaluator import Evaluator
from odigos.core.evolution import EvolutionEngine
from odigos.db import Database


@pytest_asyncio.fixture
async def db():
    d = Database(":memory:", migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


@pytest.fixture
def sections_dir():
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, "identity.md"), "w").write(
            "---\npriority: 10\nalways_include: true\n---\nYou are Odigos."
        )
        open(os.path.join(d, "voice.md"), "w").write(
            "---\npriority: 20\nalways_include: true\n---\nBe concise."
        )
        yield d


@pytest.fixture
def mock_provider():
    provider = AsyncMock()
    provider.fallback_model = "test-model"
    # C.1 rubric, C.2 score -- cycle through these
    provider.complete = AsyncMock(side_effect=[
        AsyncMock(content=json.dumps({
            "task_type": "general",
            "criteria": [{"name": "quality", "weight": 1.0, "description": "good"}],
            "notes": "test",
        })),
        AsyncMock(content=json.dumps({
            "scores": [{"criterion": "quality", "score": 9, "observation": "excellent"}],
            "overall": 9.0,
            "improvement_signal": None,
        })),
    ])
    return provider


@pytest.mark.asyncio
async def test_full_cycle_promote(db, sections_dir, mock_provider):
    """Trial that performs well gets promoted and changes persist to disk."""
    checkpoint_mgr = CheckpointManager(db=db, sections_dir=sections_dir, personality_path="")
    evaluator = Evaluator(db=db, provider=mock_provider)
    engine = EvolutionEngine(
        db=db, checkpoint_manager=checkpoint_mgr,
        evaluator=evaluator, provider=mock_provider,
    )

    # Seed some baseline evaluations so _get_baseline_score returns a value
    for i in range(5):
        await db.execute(
            "INSERT INTO evaluations (id, overall_score, created_at) VALUES (?, ?, datetime('now'))",
            (str(uuid.uuid4()), 6.0),
        )

    # Create a conversation with messages to score
    conv_id = str(uuid.uuid4())
    await db.execute("INSERT INTO conversations (id, channel) VALUES (?, ?)", (conv_id, "test"))
    user_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO messages (id, conversation_id, role, content, timestamp) VALUES (?, ?, ?, ?, ?)",
        (user_id, conv_id, "user", "Help me write Python", datetime.now(timezone.utc).isoformat()),
    )
    asst_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO messages (id, conversation_id, role, content, timestamp) VALUES (?, ?, ?, ?, ?)",
        (asst_id, conv_id, "assistant", "Here is the code...",
         (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()),
    )
    # Add positive follow-up for implicit feedback
    await db.execute(
        "INSERT INTO messages (id, conversation_id, role, content, timestamp) VALUES (?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), conv_id, "user", "Thanks, perfect!",
         (datetime.now(timezone.utc) + timedelta(seconds=2)).isoformat()),
    )

    # Create trial
    trial_id = await engine.create_trial(
        hypothesis="Improved voice for coding",
        target="prompt_section",
        change_description="More technical voice",
        overrides={"voice": "Be precise and technical."},
    )

    # Verify override is active
    sections = await checkpoint_mgr.get_working_sections()
    voice = [s for s in sections if s.name == "voice"][0]
    assert voice.content == "Be precise and technical."

    # Score the action
    scored = await engine.score_past_actions(limit=1)
    assert scored == 1

    # Simulate enough good evaluations to trigger promotion
    await db.execute(
        "UPDATE trials SET evaluation_count = 6, avg_score = 8.5 WHERE id = ?",
        (trial_id,),
    )

    # Check trial -- should promote
    result = await engine.check_active_trial()
    assert result == "promoted"

    # Verify written to disk
    voice_content = open(os.path.join(sections_dir, "voice.md")).read()
    assert "Be precise and technical." in voice_content

    # Verify no more overrides
    overrides = await db.fetch_all("SELECT * FROM trial_overrides WHERE trial_id = ?", (trial_id,))
    assert len(overrides) == 0


@pytest.mark.asyncio
async def test_full_cycle_revert(db, sections_dir, mock_provider):
    """Trial that performs poorly gets reverted, disk unchanged."""
    checkpoint_mgr = CheckpointManager(db=db, sections_dir=sections_dir, personality_path="")
    evaluator = Evaluator(db=db, provider=mock_provider)
    engine = EvolutionEngine(
        db=db, checkpoint_manager=checkpoint_mgr,
        evaluator=evaluator, provider=mock_provider,
    )

    # Override mock_provider for revert path: lessons generation
    mock_provider.complete = AsyncMock(return_value=AsyncMock(
        content="The change was too aggressive for this context."
    ))

    original_voice = open(os.path.join(sections_dir, "voice.md")).read()

    # Seed baseline evaluations
    for i in range(5):
        await db.execute(
            "INSERT INTO evaluations (id, overall_score, created_at) VALUES (?, ?, datetime('now'))",
            (str(uuid.uuid4()), 6.0),
        )

    trial_id = await engine.create_trial(
        hypothesis="Be extremely terse",
        target="prompt_section",
        change_description="Minimal responses",
        overrides={"voice": "One word answers only."},
    )

    # Simulate bad evaluations
    await db.execute(
        "UPDATE trials SET evaluation_count = 6, avg_score = 3.0, "
        "baseline_avg_score = 6.0 WHERE id = ?",
        (trial_id,),
    )

    result = await engine.check_active_trial()
    assert result == "reverted"

    # Disk unchanged
    current_voice = open(os.path.join(sections_dir, "voice.md")).read()
    assert current_voice == original_voice

    # Failed trial logged
    failed = await engine.get_failed_trials()
    assert len(failed) == 1
    assert failed[0]["hypothesis"] == "Be extremely terse"
