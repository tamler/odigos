"""Tests for agent spawn API endpoints."""
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

from odigos.api.agents import router as agents_router
from odigos.db import Database


@pytest_asyncio.fixture
async def db():
    d = Database(":memory:", migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


@pytest_asyncio.fixture
async def app(db):
    app = FastAPI()
    app.state.db = db
    app.state.settings = SimpleNamespace(api_key="test-key")

    mock_spawner = AsyncMock()
    mock_spawner.spawn = AsyncMock(return_value={
        "spawn_id": "spawn-123",
        "config": {"agent": {"name": "CodeBot"}},
        "identity": "You are a coding specialist.",
        "seed_knowledge": [],
    })
    app.state.spawner = mock_spawner
    app.include_router(agents_router)
    return app


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c.headers["Authorization"] = "Bearer test-key"
        yield c


@pytest.mark.asyncio
async def test_spawn_agent(client):
    resp = await client.post("/api/agents/spawn", json={
        "agent_name": "CodeBot",
        "role": "backend_dev",
        "description": "Python backend specialist",
        "specialty": "coding",
        "deploy_target": "vps-1",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["spawn_id"] == "spawn-123"


@pytest.mark.asyncio
async def test_list_spawned_agents(client, db):
    # Insert a deploy target and spawned agent
    await db.execute(
        "INSERT INTO deploy_targets (name, host, method) VALUES (?, ?, ?)",
        ("vps-1", "100.64.0.1", "docker"),
    )
    await db.execute(
        "INSERT INTO spawned_agents (id, agent_name, role, deploy_target, status) VALUES (?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), "CodeBot", "backend_dev", "vps-1", "running"),
    )
    resp = await client.get("/api/agents/spawned")
    assert resp.status_code == 200
    assert len(resp.json()["agents"]) == 1


@pytest.mark.asyncio
async def test_list_deploy_targets(client, db):
    await db.execute(
        "INSERT INTO deploy_targets (name, host, method) VALUES (?, ?, ?)",
        ("vps-1", "100.64.0.1", "docker"),
    )
    resp = await client.get("/api/agents/deploy-targets")
    assert resp.status_code == 200
    assert len(resp.json()["targets"]) == 1
