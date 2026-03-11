"""Tests for specialist agent spawning."""
import json
import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from odigos.core.spawner import Spawner
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
    provider.complete = AsyncMock(return_value=AsyncMock(
        content="You are a Python backend specialist focused on writing clean, efficient server-side code."
    ))
    return provider


@pytest.mark.asyncio
async def test_generate_config(db, mock_provider):
    spawner = Spawner(db=db, provider=mock_provider, parent_name="Odigos")

    config = await spawner.generate_config(
        agent_name="CodeBot",
        role="backend_dev",
        description="Python backend specialist",
        specialty="coding",
        deploy_target="vps-1",
    )

    assert config["agent"]["name"] == "CodeBot"
    assert config["agent"]["role"] == "backend_dev"
    assert config["agent"]["parent"] == "Odigos"
    assert config["agent"]["description"] == "Python backend specialist"


@pytest.mark.asyncio
async def test_generate_seed_identity(db, mock_provider):
    spawner = Spawner(db=db, provider=mock_provider, parent_name="Odigos")

    identity = await spawner.generate_seed_identity(
        role="backend_dev",
        description="Python backend specialist",
        specialty="coding",
    )

    assert len(identity) > 0
    mock_provider.complete.assert_called_once()


@pytest.mark.asyncio
async def test_gather_seed_knowledge(db, mock_provider):
    """Should gather relevant memories filtered by task type."""
    spawner = Spawner(db=db, provider=mock_provider, parent_name="Odigos")

    # Insert some evaluations to simulate knowledge
    for i in range(5):
        await db.execute(
            "INSERT INTO evaluations (id, task_type, overall_score, improvement_signal, created_at) "
            "VALUES (?, ?, ?, ?, datetime('now'))",
            (str(uuid.uuid4()), "coding", 7.0 + i * 0.5, f"Insight {i}"),
        )
    for i in range(3):
        await db.execute(
            "INSERT INTO evaluations (id, task_type, overall_score, created_at) "
            "VALUES (?, ?, ?, datetime('now'))",
            (str(uuid.uuid4()), "scheduling", 8.0),
        )

    knowledge = await spawner.gather_seed_knowledge("coding")
    assert len(knowledge) > 0
    # Should only include coding evaluations
    assert all("coding" in k.get("task_type", "") for k in knowledge)


@pytest.mark.asyncio
async def test_record_spawn(db, mock_provider):
    spawner = Spawner(db=db, provider=mock_provider, parent_name="Odigos")

    # Insert a deploy target
    await db.execute(
        "INSERT INTO deploy_targets (name, host, method) VALUES (?, ?, ?)",
        ("vps-1", "100.64.0.1", "docker"),
    )

    spawn_id = await spawner.record_spawn(
        agent_name="CodeBot",
        role="backend_dev",
        description="Python backend specialist",
        deploy_target="vps-1",
        config_snapshot={"agent": {"name": "CodeBot"}},
    )

    row = await db.fetch_one("SELECT * FROM spawned_agents WHERE id = ?", (spawn_id,))
    assert row is not None
    assert row["agent_name"] == "CodeBot"
    assert row["status"] == "deploying"
