"""Tests for the evolution API endpoints."""
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

from odigos.api.evolution import router as evolution_router
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
    app.state.checkpoint_manager = AsyncMock()
    app.state.evolution_engine = AsyncMock()
    app.include_router(evolution_router)
    return app


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c.headers["Authorization"] = "Bearer test-key"
        yield c


@pytest.mark.asyncio
async def test_get_evolution_status(client, db):
    cp_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO checkpoints (id, label) VALUES (?, ?)", (cp_id, "test")
    )
    trial_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO trials (id, checkpoint_id, hypothesis, target, expires_at, status) "
        "VALUES (?, ?, ?, ?, datetime('now', '+1 day'), 'active')",
        (trial_id, cp_id, "test hypothesis", "prompt_section"),
    )
    for i in range(3):
        await db.execute(
            "INSERT INTO evaluations (id, overall_score, created_at) VALUES (?, ?, datetime('now'))",
            (str(uuid.uuid4()), 7.0),
        )

    resp = await client.get("/api/evolution/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["active_trial"] is not None
    assert data["recent_eval_count"] == 3


@pytest.mark.asyncio
async def test_get_evaluations(client, db):
    for i in range(5):
        await db.execute(
            "INSERT INTO evaluations (id, task_type, overall_score, implicit_feedback, created_at) "
            "VALUES (?, ?, ?, ?, datetime('now'))",
            (str(uuid.uuid4()), "general", 6.0 + i, 0.3),
        )
    resp = await client.get("/api/evolution/evaluations?limit=3")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["evaluations"]) == 3


@pytest.mark.asyncio
async def test_get_directions(client, db):
    await db.execute(
        "INSERT INTO direction_log (id, analysis, direction, confidence, created_at) "
        "VALUES (?, ?, ?, ?, datetime('now'))",
        (str(uuid.uuid4()), "Doing well", "Keep going", 0.8),
    )
    resp = await client.get("/api/evolution/directions")
    assert resp.status_code == 200
    assert len(resp.json()["directions"]) == 1


@pytest.mark.asyncio
async def test_get_proposals(client, db):
    await db.execute(
        "INSERT INTO specialization_proposals (id, proposed_by, role, description, status) "
        "VALUES (?, ?, ?, ?, 'pending')",
        (str(uuid.uuid4()), "strategist", "coder", "Coding specialist"),
    )
    resp = await client.get("/api/proposals")
    assert resp.status_code == 200
    assert len(resp.json()["proposals"]) == 1


@pytest.mark.asyncio
async def test_approve_proposal(client, db):
    pid = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO specialization_proposals (id, proposed_by, role, description, status) "
        "VALUES (?, ?, ?, ?, 'pending')",
        (pid, "strategist", "coder", "Coding specialist"),
    )
    resp = await client.post(f"/api/proposals/{pid}/approve")
    assert resp.status_code == 200
    row = await db.fetch_one("SELECT status FROM specialization_proposals WHERE id = ?", (pid,))
    assert row["status"] == "approved"
