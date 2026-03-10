"""Tests for system metrics API endpoint."""

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from odigos.api.metrics import router
from odigos.db import Database


def _make_app(db: Database) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.db = db
    app.state.settings = type("S", (), {"api_key": "test-key"})()
    return app


@pytest_asyncio.fixture
async def db(tmp_db_path: str) -> Database:
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


@pytest.mark.asyncio
async def test_metrics_empty_db(client: AsyncClient):
    resp = await client.get("/api/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert data["conversation_count"] == 0
    assert data["message_count"] == 0
    assert data["total_cost_usd"] == 0.0


@pytest.mark.asyncio
async def test_metrics_with_data(client: AsyncClient, db: Database):
    await db.execute(
        "INSERT INTO conversations (id, channel, started_at, last_message_at, message_count) "
        "VALUES (?, ?, ?, ?, ?)",
        ("c1", "telegram", "2026-01-01 00:00:00", "2026-01-01 01:00:00", 2),
    )
    await db.execute(
        "INSERT INTO conversations (id, channel, started_at, last_message_at, message_count) "
        "VALUES (?, ?, ?, ?, ?)",
        ("c2", "telegram", "2026-01-02 00:00:00", "2026-01-02 01:00:00", 1),
    )
    await db.execute(
        "INSERT INTO messages (id, conversation_id, role, content, cost_usd, timestamp) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("m1", "c1", "user", "Hello", 0.01, "2026-01-01 00:00:00"),
    )
    await db.execute(
        "INSERT INTO messages (id, conversation_id, role, content, cost_usd, timestamp) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("m2", "c1", "assistant", "Hi!", 0.05, "2026-01-01 00:01:00"),
    )
    await db.execute(
        "INSERT INTO messages (id, conversation_id, role, content, cost_usd, timestamp) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("m3", "c2", "user", "Hey", 0.02, "2026-01-02 00:00:00"),
    )

    resp = await client.get("/api/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert data["conversation_count"] == 2
    assert data["message_count"] == 3
    assert abs(data["total_cost_usd"] - 0.08) < 1e-9
