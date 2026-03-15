"""Tests for agent-to-agent WebSocket endpoint."""
import json
from unittest.mock import AsyncMock, MagicMock
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import FastAPI
from starlette.testclient import TestClient

from odigos.api.agent_ws import router as agent_ws_router


@pytest_asyncio.fixture
async def app():
    from odigos.db import Database
    from odigos.core.agent_client import AgentClient

    db = Database(":memory:", migrations_dir="migrations")
    await db.initialize()

    app = FastAPI()
    app.state.db = db
    app.state.agent_client = AgentClient(peers=[], agent_name="TestAgent", db=db)
    app.state.settings = SimpleNamespace(api_key="test-key")
    app.include_router(agent_ws_router)
    return app


def test_agent_ws_rejects_without_auth(app):
    client = TestClient(app)
    with client.websocket_connect("/ws/agent") as ws:
        # Send an auth message with an invalid token
        ws.send_json({"type": "auth", "token": "bad-token"})
        # Server should respond with an error and close the connection
        response = ws.receive_json()
        assert response["type"] == "error"
        assert response["payload"]["message"] == "Unauthorized"


def test_agent_ws_accepts_with_auth(app):
    client = TestClient(app)
    with client.websocket_connect("/ws/agent?token=test-key") as ws:
        ws.send_json({
            "type": "status_ping",
            "from_agent": "Archie",
            "content": "",
        })
        response = ws.receive_json()
        assert response["type"] == "status_pong"
