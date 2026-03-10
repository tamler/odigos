"""Tests for goals, todos, and reminders API endpoints."""

from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from odigos.api.goals import router
from odigos.core.goal_store import GoalStore
from odigos.db import Database


def _make_app(db: Database, store: GoalStore) -> FastAPI:
    """Create a minimal FastAPI app with the goals router and fake state."""
    app = FastAPI()
    app.include_router(router)
    app.state.db = db
    app.state.goal_store = store
    app.state.settings = SimpleNamespace(api_key="test-key")
    return app


@pytest_asyncio.fixture
async def db(tmp_db_path: str) -> Database:
    d = Database(tmp_db_path, migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


@pytest_asyncio.fixture
async def store(db: Database) -> GoalStore:
    return GoalStore(db=db)


@pytest_asyncio.fixture
async def client(db: Database, store: GoalStore) -> AsyncClient:
    app = _make_app(db, store)
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": "Bearer test-key"},
    ) as c:
        yield c


# --- Goals ---


@pytest.mark.asyncio
async def test_list_goals_empty(client: AsyncClient):
    resp = await client.get("/api/goals")
    assert resp.status_code == 200
    assert resp.json() == {"goals": []}


@pytest.mark.asyncio
async def test_list_goals_with_data(client: AsyncClient, store: GoalStore):
    await store.create_goal("Learn FastAPI")
    await store.create_goal("Build REST API")

    resp = await client.get("/api/goals", params={"status": "active"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["goals"]) == 2
    descriptions = [g["description"] for g in data["goals"]]
    assert "Learn FastAPI" in descriptions
    assert "Build REST API" in descriptions


# --- Todos ---


@pytest.mark.asyncio
async def test_list_todos_empty(client: AsyncClient):
    resp = await client.get("/api/todos")
    assert resp.status_code == 200
    assert resp.json() == {"todos": []}


@pytest.mark.asyncio
async def test_list_todos_with_data(client: AsyncClient, store: GoalStore):
    await store.create_todo("Write tests")
    await store.create_todo("Implement endpoints")

    resp = await client.get("/api/todos", params={"status": "pending"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["todos"]) == 2
    descriptions = [t["description"] for t in data["todos"]]
    assert "Write tests" in descriptions
    assert "Implement endpoints" in descriptions


# --- Reminders ---


@pytest.mark.asyncio
async def test_list_reminders_empty(client: AsyncClient):
    resp = await client.get("/api/reminders")
    assert resp.status_code == 200
    assert resp.json() == {"reminders": []}


@pytest.mark.asyncio
async def test_list_reminders_with_data(client: AsyncClient, store: GoalStore):
    await store.create_reminder("Check deployment")
    await store.create_reminder("Review PR")

    resp = await client.get("/api/reminders", params={"status": "pending"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["reminders"]) == 2
    descriptions = [r["description"] for r in data["reminders"]]
    assert "Check deployment" in descriptions
    assert "Review PR" in descriptions
