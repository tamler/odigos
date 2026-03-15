"""Tests for the POST /api/agent/peer/announce discovery endpoint."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from odigos.api.agent_message import router


def _make_app(api_key: str = "test-key", db=None, known_peer: bool = False) -> FastAPI:
    """Create a minimal FastAPI app with the agent_message router and fake state."""
    app = FastAPI()
    app.include_router(router)
    app.state.settings = SimpleNamespace(api_key=api_key)
    if db is None:
        db = MagicMock()
        if known_peer:
            db.fetch_one = AsyncMock(return_value={"agent_name": "planner-bot"})
        else:
            db.fetch_one = AsyncMock(return_value=None)
        db.execute = AsyncMock()
    app.state.db = db
    return app


@pytest_asyncio.fixture
async def client() -> AsyncClient:
    app = _make_app(known_peer=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": "Bearer test-key"},
    ) as c:
        yield c


@pytest.mark.asyncio
async def test_announce_new_peer(client: AsyncClient):
    """Announce from a known peer (already in agent_registry) succeeds."""
    resp = await client.post(
        "/api/agent/peer/announce",
        json={
            "agent_name": "planner-bot",
            "ws_host": "100.64.0.5",
            "ws_port": 8001,
            "role": "planner",
            "description": "Planning specialist",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "planner-bot" in data["message"]


@pytest.mark.asyncio
async def test_announce_unknown_peer_rejected():
    """Announce from an unknown agent is rejected with 403."""
    app = _make_app(known_peer=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": "Bearer test-key"},
    ) as c:
        resp = await c.post(
            "/api/agent/peer/announce",
            json={
                "agent_name": "unknown-bot",
                "ws_host": "100.64.0.9",
            },
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_announce_updates_existing_peer():
    db = MagicMock()
    db.fetch_one = AsyncMock(return_value={"agent_name": "planner-bot"})
    db.execute = AsyncMock()
    app = _make_app(db=db)
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": "Bearer test-key"},
    ) as c:
        resp = await c.post(
            "/api/agent/peer/announce",
            json={
                "agent_name": "planner-bot",
                "ws_host": "100.64.0.5",
                "role": "planner",
            },
        )
    assert resp.status_code == 200
    # Should have called UPDATE, not INSERT
    call_args = db.execute.call_args[0][0]
    assert "UPDATE" in call_args


@pytest.mark.asyncio
async def test_announce_missing_agent_name(client: AsyncClient):
    resp = await client.post(
        "/api/agent/peer/announce",
        json={"ws_host": "100.64.0.5"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_auth_required_when_api_key_configured():
    app = _make_app(api_key="secret-key")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post(
            "/api/agent/peer/announce",
            json={"agent_name": "planner-bot", "ws_host": "100.64.0.5"},
        )
    assert resp.status_code == 401
