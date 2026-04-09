"""Tests for /api/plans/active endpoint."""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from odigos.api.plans import router
from odigos.container import Container
from odigos.db import Database


def _make_app(db: Database) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    container = Container(
        db=db,
        settings=SimpleNamespace(api_key="test-key"),
    )
    app.state.container = container
    return app


@pytest_asyncio.fixture
async def db(tmp_db_path: str):
    d = Database(tmp_db_path, migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


@pytest_asyncio.fixture
async def client(db: Database) -> AsyncClient:
    app = _make_app(db)
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": "Bearer test-key"},
    ) as c:
        yield c


async def _seed_plan(db, goal: str, steps: list[dict], status: str = "in_progress"):
    plan_id = str(uuid.uuid4())
    conv_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO conversations (id, channel) VALUES (?, ?)",
        (conv_id, "test"),
    )
    now = "2026-04-09T00:00:00"
    await db.execute(
        "INSERT INTO task_plans (id, conversation_id, goal, steps, status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (plan_id, conv_id, goal, json.dumps(steps), status, now, now),
    )
    return plan_id


class TestPlansActive:
    async def test_returns_in_progress_plans_with_step_counts(self, client: AsyncClient, db):
        steps = [
            {"step": 1, "task": "First step", "status": "done"},
            {"step": 2, "task": "Second step", "status": "done"},
            {"step": 3, "task": "Third step", "status": "in_progress"},
            {"step": 4, "task": "Fourth step", "status": "pending"},
            {"step": 5, "task": "Fifth step", "status": "pending"},
        ]
        await _seed_plan(db, "Ship the feature", steps)

        resp = await client.get("/api/plans/active")
        assert resp.status_code == 200
        data = resp.json()
        assert "plans" in data
        assert len(data["plans"]) == 1
        plan = data["plans"][0]
        assert plan["goal"] == "Ship the feature"
        assert plan["current_step"] == 3
        assert plan["total_steps"] == 5

    async def test_excludes_done_plans(self, client: AsyncClient, db):
        await _seed_plan(db, "Done plan", [{"step": 1, "status": "done"}], status="done")
        await _seed_plan(db, "Active plan", [{"step": 1, "status": "pending"}])

        resp = await client.get("/api/plans/active")
        assert resp.status_code == 200
        plans = resp.json()["plans"]
        assert len(plans) == 1
        assert plans[0]["goal"] == "Active plan"

    async def test_empty_when_no_active_plans(self, client: AsyncClient, db):
        resp = await client.get("/api/plans/active")
        assert resp.status_code == 200
        assert resp.json()["plans"] == []

    async def test_handles_malformed_steps_json(self, client: AsyncClient, db):
        plan_id = str(uuid.uuid4())
        conv_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO conversations (id, channel) VALUES (?, ?)",
            (conv_id, "test"),
        )
        now = "2026-04-09T00:00:00"
        await db.execute(
            "INSERT INTO task_plans (id, conversation_id, goal, steps, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (plan_id, conv_id, "Bad plan", "not json", "in_progress", now, now),
        )
        resp = await client.get("/api/plans/active")
        assert resp.status_code == 200
        plans = resp.json()["plans"]
        # Malformed plan should still appear but with 0/0 step counts
        assert len(plans) == 1
        assert plans[0]["current_step"] == 0
        assert plans[0]["total_steps"] == 0
