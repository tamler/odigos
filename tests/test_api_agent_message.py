"""Tests for the POST /api/agent/message peer endpoint."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from odigos.api.agent_message import router


def _make_app(agent: MagicMock, api_key: str = "") -> FastAPI:
    """Create a minimal FastAPI app with the agent_message router and fake state."""
    app = FastAPI()
    app.include_router(router)
    app.state.agent = agent
    app.state.settings = SimpleNamespace(api_key=api_key)
    return app


@pytest.fixture
def agent() -> MagicMock:
    mock = MagicMock()
    mock.handle_message = AsyncMock(return_value="Peer response")
    return mock


@pytest_asyncio.fixture
async def client(agent: MagicMock) -> AsyncClient:
    app = _make_app(agent)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_receive_peer_message(client: AsyncClient, agent: MagicMock):
    resp = await client.post(
        "/api/agent/message",
        json={"from_agent": "planner-bot", "content": "Please summarize the report"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["response"] == "Peer response"

    # Verify UniversalMessage was created with channel="peer"
    agent.handle_message.assert_awaited_once()
    msg = agent.handle_message.call_args[0][0]
    assert msg.channel == "peer"
    assert msg.sender == "planner-bot"
    assert msg.metadata["chat_id"] == "planner-bot"


@pytest.mark.asyncio
async def test_missing_content(client: AsyncClient):
    resp = await client.post(
        "/api/agent/message",
        json={"from_agent": "planner-bot"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_help_request_type(client: AsyncClient, agent: MagicMock):
    resp = await client.post(
        "/api/agent/message",
        json={
            "from_agent": "helper-bot",
            "message_type": "help_request",
            "content": "I need assistance",
        },
    )
    assert resp.status_code == 200

    msg = agent.handle_message.call_args[0][0]
    assert msg.metadata["message_type"] == "help_request"
    assert "[help_request from helper-bot]" in msg.content


@pytest.mark.asyncio
async def test_auth_required_when_api_key_configured(agent: MagicMock):
    app = _make_app(agent, api_key="secret-key")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post(
            "/api/agent/message",
            json={"from_agent": "planner-bot", "content": "hello"},
        )
    assert resp.status_code == 401
