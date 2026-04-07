"""Tests for the WebSocket endpoint at /api/chat."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from odigos.api.ws import router
from odigos.container import Container


def _make_app(api_key: str = "", agent: Optional[MagicMock] = None) -> FastAPI:
    """Create a minimal FastAPI app with the ws router and fake state.

    Mirrors real app state from main.py: agent_service (not agent).
    """
    app = FastAPI()
    app.include_router(router)

    if agent is None:
        agent = MagicMock()
        agent.handle_message = AsyncMock(return_value="Agent response")
        agent.db = MagicMock()
        agent.executor = MagicMock()
        agent.executor.provider = MagicMock()

    agent_service = MagicMock()
    agent_service.handle_message = agent.handle_message
    agent_service.agent = agent

    web_channel = MagicMock()
    web_channel.register_connection = MagicMock()
    web_channel.unregister_connection = MagicMock()
    web_channel.add_subscription = MagicMock()

    message_bus = MagicMock()
    message_bus.create_conversation = AsyncMock(return_value="abc123def456")

    app.state.container = Container(
        settings=SimpleNamespace(api_key=api_key),
        agent_service=agent_service,
        web_channel=web_channel,
        message_bus=message_bus,
    )
    return app


class TestAuthNoToken:
    """Connection closed when invalid auth message is sent."""

    def test_no_token_when_required(self):
        app = _make_app(api_key="secret-key")
        client = TestClient(app)
        with client.websocket_connect("/api/chat") as ws:
            # Server accepted, waiting for first-message auth
            ws.send_json({"type": "auth", "token": "wrong-key"})
            error = ws.receive_json()
            assert error["type"] == "error"
            assert "Invalid" in error["message"]


class TestAuthWrongToken:
    """Connection closed when token is wrong."""

    def test_wrong_token(self):
        app = _make_app(api_key="secret-key")
        client = TestClient(app)
        with pytest.raises(Exception):
            with client.websocket_connect("/api/chat?token=wrong-key"):
                pass


class TestAuthValidToken:
    """Connection succeeds with valid token."""

    def test_valid_token(self):
        app = _make_app(api_key="secret-key")
        client = TestClient(app)
        with client.websocket_connect("/api/chat?token=secret-key") as ws:
            data = ws.receive_json()
            assert data["type"] == "connected"
            assert "session_id" in data
            assert "conversation_id" not in data  # No conversation until first message


class TestAuthNoKeyConfigured:
    """Connection denied when no api_key is configured."""

    def test_no_key_configured(self):
        app = _make_app(api_key="")
        client = TestClient(app)
        with pytest.raises(Exception):
            with client.websocket_connect("/api/chat"):
                pass  # should not reach here


class TestChatMessage:
    """Chat message is forwarded to the agent and response is returned."""

    def test_chat_message_returns_agent_response(self):
        agent = MagicMock()
        agent.handle_message = AsyncMock(return_value="Hello from agent")
        agent.db = MagicMock()
        agent.executor = MagicMock()
        agent.executor.provider = MagicMock()
        app = _make_app(api_key="test-key", agent=agent)
        client = TestClient(app)
        with client.websocket_connect("/api/chat?token=test-key") as ws:
            connected = ws.receive_json()
            session_id = connected["session_id"]

            ws.send_json({"type": "chat", "content": "Hi there"})

            # First message on a new conversation is conversation_started
            started = ws.receive_json()
            assert started["type"] == "conversation_started"
            # conversation_id is now a plain UUID from MessageBus
            chat_conv_id = started["conversation_id"]
            assert chat_conv_id == "abc123def456"

            response = ws.receive_json()
            assert response["type"] == "chat_response"
            assert response["content"] == "Hello from agent"
            assert response["conversation_id"] == chat_conv_id

            agent.handle_message.assert_awaited_once()
            call_msg = agent.handle_message.call_args[0][0]
            assert call_msg.channel == "web"
            assert call_msg.sender == session_id
            assert call_msg.content == "Hi there"


class TestChatConversationId:
    """Chat auto-generates a plain UUID conversation_id via MessageBus."""

    def test_chat_auto_generates_conversation_id(self):
        app = _make_app(api_key="test-key")
        client = TestClient(app)
        with client.websocket_connect("/api/chat?token=test-key") as ws:
            data = ws.receive_json()
            assert data["type"] == "connected"
            assert "session_id" in data
            # conversation_id is NOT in connected event -- only after first message
            assert "conversation_id" not in data


class TestSubscribe:
    """Subscribe command returns subscribed response and registers channels."""

    def test_subscribe_command(self):
        app = _make_app(api_key="test-key")
        client = TestClient(app)
        with client.websocket_connect("/api/chat?token=test-key") as ws:
            connected = ws.receive_json()
            session_id = connected["session_id"]

            ws.send_json({"type": "subscribe", "channels": ["events", "logs"]})
            response = ws.receive_json()

            assert response["type"] == "subscribed"
            assert response["channels"] == ["events", "logs"]

            web_channel = app.state.container.web_channel
            assert web_channel.add_subscription.call_count == 2
            # Before any chat, subscription uses session_id as key
            calls = web_channel.add_subscription.call_args_list
            assert calls[0][0][0] == session_id
            assert calls[1][0][0] == session_id
