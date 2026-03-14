"""Tests for the agent state inspector API endpoint."""
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

from odigos.api.state import router as state_router
from odigos.core.agent import Agent
from odigos.core.budget import BudgetTracker
from odigos.db import Database
from odigos.providers.base import LLMProvider, LLMResponse
from odigos.skills.registry import SkillRegistry
from odigos.tools.registry import ToolRegistry


class StubLLMProvider(LLMProvider):
    """Minimal LLM provider for testing -- never called, just satisfies the interface."""

    async def complete(self, messages, **kwargs):
        return LLMResponse(content="stub", tokens_in=0, tokens_out=0)


@pytest_asyncio.fixture
async def db():
    d = Database(":memory:", migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


@pytest_asyncio.fixture
async def app(db):
    app = FastAPI()

    settings = SimpleNamespace(
        agent=SimpleNamespace(name="TestAgent", role="tester"),
        api_key="test-key",
    )
    app.state.settings = settings
    app.state.db = db

    budget_tracker = BudgetTracker(db=db, daily_limit=5.00, monthly_limit=50.00)
    app.state.budget_tracker = budget_tracker

    tool_registry = ToolRegistry()
    skill_registry = SkillRegistry()

    provider = StubLLMProvider()
    agent = Agent(
        db=db,
        provider=provider,
        agent_name="TestAgent",
        tool_registry=tool_registry,
        skill_registry=skill_registry,
        budget_tracker=budget_tracker,
    )
    app.state.agent = agent
    app.state.skill_registry = skill_registry
    app.state.plugin_manager = SimpleNamespace(loaded_plugins=[])

    app.include_router(state_router)
    return app


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c.headers["Authorization"] = "Bearer test-key"
        yield c


@pytest_asyncio.fixture
async def unauthed_client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_state_returns_all_sections(client):
    resp = await client.get("/api/state")
    assert resp.status_code == 200
    data = resp.json()

    expected_sections = [
        "agent", "budget", "memory", "conversations",
        "tools", "skills", "plugins", "evolution",
        "heartbeat", "system",
    ]
    for section in expected_sections:
        assert section in data, f"Missing section: {section}"


@pytest.mark.asyncio
async def test_state_agent_info(client):
    resp = await client.get("/api/state")
    data = resp.json()
    agent = data["agent"]
    assert agent["name"] == "TestAgent"
    assert agent["role"] == "tester"
    assert "uptime" in agent
    assert "uptime_seconds" in agent
    assert agent["uptime_seconds"] >= 0


@pytest.mark.asyncio
async def test_state_budget_info(client):
    resp = await client.get("/api/state")
    data = resp.json()
    budget = data["budget"]
    assert budget["daily_limit"] == 5.00
    assert budget["monthly_limit"] == 50.00
    assert budget["within_budget"] is True
    assert isinstance(budget["daily_spend"], (int, float))
    assert isinstance(budget["monthly_spend"], (int, float))


@pytest.mark.asyncio
async def test_state_system_info(client):
    resp = await client.get("/api/state")
    data = resp.json()
    system = data["system"]
    assert "python_version" in system
    assert "platform" in system
    assert isinstance(system["pid"], int)
    assert system["pid"] > 0


@pytest.mark.asyncio
async def test_state_conversations_and_memory(client, db):
    # Insert a conversation and message to verify counting
    import uuid
    conv_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO conversations (id, channel, started_at, last_message_at) "
        "VALUES (?, 'test', datetime('now'), datetime('now'))",
        (conv_id,),
    )
    await db.execute(
        "INSERT INTO messages (id, conversation_id, role, content, timestamp) "
        "VALUES (?, ?, 'user', 'hello', datetime('now'))",
        (str(uuid.uuid4()), conv_id),
    )

    resp = await client.get("/api/state")
    data = resp.json()
    assert data["conversations"]["total"] >= 1
    assert data["conversations"]["recent_messages_1h"] >= 1


@pytest.mark.asyncio
async def test_state_tools_and_skills(client):
    resp = await client.get("/api/state")
    data = resp.json()
    assert isinstance(data["tools"], list)
    assert isinstance(data["skills"], list)
    assert isinstance(data["plugins"], list)


@pytest.mark.asyncio
async def test_state_evolution_info(client, db):
    import uuid
    # Insert an evaluation
    await db.execute(
        "INSERT INTO evaluations (id, overall_score, created_at) VALUES (?, ?, datetime('now'))",
        (str(uuid.uuid4()), 8.0),
    )
    resp = await client.get("/api/state")
    data = resp.json()
    evo = data["evolution"]
    assert evo["evaluation_count"] >= 1
    assert evo["recent_avg_score"] is not None
    assert evo["recent_avg_score"] == 8.0


@pytest.mark.asyncio
async def test_state_requires_auth(unauthed_client):
    resp = await unauthed_client.get("/api/state")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_state_rejects_wrong_key(unauthed_client):
    resp = await unauthed_client.get(
        "/api/state",
        headers={"Authorization": "Bearer wrong-key"},
    )
    assert resp.status_code == 403
