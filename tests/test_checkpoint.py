"""Tests for the checkpoint manager (deadman switch)."""
import json
import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from odigos.core.checkpoint import CheckpointManager
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
        (open(os.path.join(d, "identity.md"), "w")).write(
            "---\npriority: 10\nalways_include: true\n---\nYou are Odigos."
        )
        (open(os.path.join(d, "voice.md"), "w")).write(
            "---\npriority: 20\nalways_include: true\n---\nBe concise."
        )
        yield d


@pytest.mark.asyncio
async def test_create_checkpoint(db, sections_dir):
    mgr = CheckpointManager(db=db, sections_dir=sections_dir, personality_path="")
    cp_id = await mgr.create_checkpoint(label="initial")
    assert cp_id is not None
    row = await db.fetch_one("SELECT * FROM checkpoints WHERE id = ?", (cp_id,))
    assert row["label"] == "initial"
    snapshot = json.loads(row["prompt_sections_snapshot"])
    assert "identity" in snapshot
    assert "voice" in snapshot


@pytest.mark.asyncio
async def test_get_working_sections_no_trial(db, sections_dir):
    mgr = CheckpointManager(db=db, sections_dir=sections_dir, personality_path="")
    sections = await mgr.get_working_sections()
    names = [s.name for s in sections]
    assert "identity" in names
    assert "voice" in names


@pytest.mark.asyncio
async def test_get_working_sections_with_active_override(db, sections_dir):
    mgr = CheckpointManager(db=db, sections_dir=sections_dir, personality_path="")
    cp_id = await mgr.create_checkpoint(label="base")
    trial_id = str(uuid.uuid4())
    expires = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    await db.execute(
        "INSERT INTO trials (id, checkpoint_id, hypothesis, target, expires_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (trial_id, cp_id, "test hypothesis", "prompt_section", expires, "active"),
    )
    override_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO trial_overrides (id, trial_id, target_type, target_name, override_content) "
        "VALUES (?, ?, ?, ?, ?)",
        (override_id, trial_id, "prompt_section", "identity", "You are an evolved agent."),
    )
    sections = await mgr.get_working_sections()
    identity = [s for s in sections if s.name == "identity"][0]
    assert identity.content == "You are an evolved agent."


@pytest.mark.asyncio
async def test_expired_override_ignored(db, sections_dir):
    mgr = CheckpointManager(db=db, sections_dir=sections_dir, personality_path="")
    cp_id = await mgr.create_checkpoint(label="base")
    trial_id = str(uuid.uuid4())
    expired = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    await db.execute(
        "INSERT INTO trials (id, checkpoint_id, hypothesis, target, expires_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (trial_id, cp_id, "expired hypothesis", "prompt_section", expired, "active"),
    )
    override_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO trial_overrides (id, trial_id, target_type, target_name, override_content) "
        "VALUES (?, ?, ?, ?, ?)",
        (override_id, trial_id, "prompt_section", "identity", "Should not appear."),
    )
    sections = await mgr.get_working_sections()
    identity = [s for s in sections if s.name == "identity"][0]
    assert identity.content == "You are Odigos."


@pytest.mark.asyncio
async def test_promote_trial_writes_to_disk(db, sections_dir):
    mgr = CheckpointManager(db=db, sections_dir=sections_dir, personality_path="")
    cp_id = await mgr.create_checkpoint(label="before-trial")
    trial_id = str(uuid.uuid4())
    expires = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    await db.execute(
        "INSERT INTO trials (id, checkpoint_id, hypothesis, target, expires_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (trial_id, cp_id, "improve identity", "prompt_section", expires, "active"),
    )
    override_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO trial_overrides (id, trial_id, target_type, target_name, override_content) "
        "VALUES (?, ?, ?, ?, ?)",
        (override_id, trial_id, "prompt_section", "identity", "You are an evolved agent."),
    )
    await mgr.promote_trial(trial_id)
    content = open(os.path.join(sections_dir, "identity.md")).read()
    assert "You are an evolved agent." in content
    row = await db.fetch_one(
        "SELECT COUNT(*) as cnt FROM trial_overrides WHERE trial_id = ?", (trial_id,)
    )
    assert row["cnt"] == 0
    trial = await db.fetch_one("SELECT status FROM trials WHERE id = ?", (trial_id,))
    assert trial["status"] == "promoted"


@pytest.mark.asyncio
async def test_revert_trial_deletes_overrides(db, sections_dir):
    mgr = CheckpointManager(db=db, sections_dir=sections_dir, personality_path="")
    cp_id = await mgr.create_checkpoint(label="base")
    trial_id = str(uuid.uuid4())
    expires = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    await db.execute(
        "INSERT INTO trials (id, checkpoint_id, hypothesis, target, expires_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (trial_id, cp_id, "bad hypothesis", "prompt_section", expires, "active"),
    )
    override_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO trial_overrides (id, trial_id, target_type, target_name, override_content) "
        "VALUES (?, ?, ?, ?, ?)",
        (override_id, trial_id, "prompt_section", "identity", "Bad content."),
    )
    await mgr.revert_trial(trial_id, reason="worse_than_baseline")
    row = await db.fetch_one(
        "SELECT COUNT(*) as cnt FROM trial_overrides WHERE trial_id = ?", (trial_id,)
    )
    assert row["cnt"] == 0
    trial = await db.fetch_one("SELECT status FROM trials WHERE id = ?", (trial_id,))
    assert trial["status"] == "reverted"
    content = open(os.path.join(sections_dir, "identity.md")).read()
    assert "You are Odigos." in content
