"""Tests for specialist agent spawning."""
import json
import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from odigos.core.spawner import Spawner
from odigos.core.template_index import AgentTemplateIndex
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
    )

    assert config["agent"]["name"] == "CodeBot"
    assert config["agent"]["role"] == "backend_dev"
    assert config["agent"]["parent"] == "Odigos"
    assert config["agent"]["description"] == "Python backend specialist"


@pytest.mark.asyncio
async def test_generate_seed_identity_no_template(db, mock_provider):
    """Without a template index, should return 'none' source with suggestion."""
    spawner = Spawner(db=db, provider=mock_provider, parent_name="Odigos")

    result = await spawner.generate_seed_identity(
        role="quantum physicist",
        description="Studies entanglement",
    )

    assert result["source"] == "none"
    assert result["identity"] == ""
    assert "No template found" in result["suggestion"]
    assert "browse_agent_templates" in result["suggestion"]
    # No LLM call wasted
    mock_provider.complete.assert_not_called()


@pytest.mark.asyncio
async def test_generate_seed_identity_with_template(db, mock_provider):
    """When a template match exists, should return tailored identity."""
    template_index = AgentTemplateIndex(db=db)
    await template_index.create_custom_template(
        name="backend architect",
        content="# Backend Architect\nYou design scalable APIs and services.",
        division="engineering",
    )

    mock_provider.complete = AsyncMock(return_value=AsyncMock(
        content="You are a backend architect who designs scalable APIs with a focus on reliability."
    ))

    spawner = Spawner(
        db=db, provider=mock_provider, parent_name="Odigos",
        template_index=template_index,
    )

    result = await spawner.generate_seed_identity(
        role="backend architect",
        description="Designs scalable APIs",
        specialty="api design",
    )

    assert result["source"] == "template"
    assert len(result["identity"]) > 0
    assert result["template_name"] == "backend architect"
    # LLM was called with higher token budget for template tailoring
    call_kwargs = mock_provider.complete.call_args
    assert call_kwargs.kwargs["max_tokens"] == 1500


@pytest.mark.asyncio
async def test_generate_seed_identity_template_index_no_match(db, mock_provider):
    """With template index but no matching template, should return suggestion."""
    template_index = AgentTemplateIndex(db=db)
    await template_index.create_custom_template(
        name="backend architect",
        content="# Backend Architect",
        division="engineering",
    )

    spawner = Spawner(
        db=db, provider=mock_provider, parent_name="Odigos",
        template_index=template_index,
    )

    result = await spawner.generate_seed_identity(
        role="quantum physicist",
        description="Studies entanglement",
        specialty="quantum mechanics",
    )

    assert result["source"] == "none"
    assert "No template found" in result["suggestion"]
    mock_provider.complete.assert_not_called()


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

    spawn_id = await spawner.record_spawn(
        agent_name="CodeBot",
        role="backend_dev",
        description="Python backend specialist",
        config_snapshot={"agent": {"name": "CodeBot"}},
    )

    row = await db.fetch_one("SELECT * FROM spawned_agents WHERE id = ?", (spawn_id,))
    assert row is not None
    assert row["agent_name"] == "CodeBot"
    assert row["status"] == "deploying"
