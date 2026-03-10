"""Tests for the POST /api/message endpoint."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from odigos.api.message import router


def _make_app(agent: MagicMock) -> FastAPI:
    """Create a minimal FastAPI app with the message router and fake state."""
    app = FastAPI()
    app.include_router(router)
    app.state.agent = agent
    app.state.settings = SimpleNamespace(api_key="")  # dev mode, no auth
    return app


@pytest.fixture
def agent() -> MagicMock:
    mock = MagicMock()
    mock.handle_message = AsyncMock(return_value="Agent response")
    return mock


@pytest_asyncio.fixture
async def client(agent: MagicMock) -> AsyncClient:
    app = _make_app(agent)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_submit_message(client: AsyncClient, agent: MagicMock):
    resp = await client.post(
        "/api/message",
        json={"content": "Hello agent", "conversation_id": "api:test123"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["response"] == "Agent response"
    assert data["conversation_id"] == "api:test123"
    agent.handle_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_auto_generates_conversation_id(client: AsyncClient, agent: MagicMock):
    resp = await client.post(
        "/api/message",
        json={"content": "Hello agent"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["response"] == "Agent response"
    # Auto-generated conversation_id should start with "api:"
    assert data["conversation_id"].startswith("api:")
    # The suffix should be 12 hex characters
    suffix = data["conversation_id"].split(":", 1)[1]
    assert len(suffix) == 12
    int(suffix, 16)  # should not raise


@pytest.mark.asyncio
async def test_missing_content(client: AsyncClient):
    resp = await client.post("/api/message", json={})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_empty_content(client: AsyncClient):
    resp = await client.post("/api/message", json={"content": ""})
    assert resp.status_code == 422
