import importlib

import pytest
from starlette.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock

pytestmark = pytest.mark.skipif(
    not importlib.util.find_spec("sentence_transformers"),
    reason="sentence_transformers not installed",
)


class TestWebSocketMounted:
    def test_ws_endpoint_exists(self):
        from odigos.main import app
        from odigos.channels.web import WebChannel
        from odigos.container import Container

        agent = MagicMock()
        agent.handle_message = AsyncMock(return_value="ok")

        tracer = MagicMock()
        tracer.subscribe = MagicMock()

        agent_service = MagicMock()
        agent_service.handle_message = agent.handle_message
        agent_service.agent = agent

        app.state.container = Container(
            settings=type("S", (), {"api_key": "test-key"})(),
            agent=agent,
            agent_service=agent_service,
            tracer=tracer,
            web_channel=WebChannel(),
        )

        client = TestClient(app)
        with client.websocket_connect("/api/chat?token=test-key") as ws:
            data = ws.receive_json()
            assert data["type"] == "connected"
            assert "session_id" in data
