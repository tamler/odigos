"""Integration tests verifying all API routers are mounted on the main app."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from httpx import ASGITransport, AsyncClient

from odigos.core.budget import BudgetStatus
from odigos.main import app


@pytest.fixture(autouse=True)
def _mock_app_state():
    """Inject mock dependencies into app.state so endpoints resolve."""
    db = AsyncMock()
    db.fetch_one = AsyncMock(return_value={"cnt": 0, "total": 0, "total_cost": 0.0})
    db.fetch_all = AsyncMock(return_value=[])

    goal_store = AsyncMock()
    goal_store.list_goals = AsyncMock(return_value=[])
    goal_store.list_todos = AsyncMock(return_value=[])
    goal_store.list_reminders = AsyncMock(return_value=[])

    agent = AsyncMock()

    vector_memory = AsyncMock()
    vector_memory.search = AsyncMock(return_value=[])

    budget_tracker = AsyncMock()
    budget_tracker.check_budget = AsyncMock(return_value=BudgetStatus(
        within_budget=True,
        warning=False,
        daily_spend=0.0,
        monthly_spend=0.0,
        daily_limit=5.0,
        monthly_limit=100.0,
    ))

    plugin_manager = MagicMock()
    plugin_manager.loaded_plugins = []

    settings = type("S", (), {"api_key": ""})()

    app.state.db = db
    app.state.goal_store = goal_store
    app.state.agent = agent
    app.state.vector_memory = vector_memory
    app.state.budget_tracker = budget_tracker
    app.state.plugin_manager = plugin_manager
    app.state.settings = settings

    yield

    # Clean up state attributes
    for attr in ("db", "goal_store", "agent", "vector_memory",
                 "budget_tracker", "plugin_manager", "settings"):
        try:
            delattr(app.state, attr)
        except AttributeError:
            pass


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_get_conversations(client):
    resp = await client.get("/api/conversations")
    assert resp.status_code == 200
    data = resp.json()
    assert "conversations" in data


@pytest.mark.asyncio
async def test_get_goals(client):
    resp = await client.get("/api/goals")
    assert resp.status_code == 200
    data = resp.json()
    assert "goals" in data


@pytest.mark.asyncio
async def test_get_budget(client):
    resp = await client.get("/api/budget")
    assert resp.status_code == 200
    data = resp.json()
    assert "within_budget" in data


@pytest.mark.asyncio
async def test_get_metrics(client):
    resp = await client.get("/api/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert "conversation_count" in data


@pytest.mark.asyncio
async def test_get_plugins(client):
    resp = await client.get("/api/plugins")
    assert resp.status_code == 200
    data = resp.json()
    assert "plugins" in data


@pytest.mark.asyncio
async def test_get_memory_entities(client):
    resp = await client.get("/api/memory/entities")
    assert resp.status_code == 200
    data = resp.json()
    assert "entities" in data


@pytest.mark.asyncio
async def test_memory_search(client):
    resp = await client.get("/api/memory/search", params={"q": "test"})
    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data
