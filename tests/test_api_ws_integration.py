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

        app.state.settings = type("S", (), {"api_key": "test-key"})()
        app.state.agent = MagicMock()
        app.state.agent.handle_message = AsyncMock(return_value="ok")
        app.state.tracer = MagicMock()
        app.state.tracer.subscribe = MagicMock()
        app.state.web_channel = WebChannel()

        client = TestClient(app)
        with client.websocket_connect("/api/ws?token=test-key") as ws:
            data = ws.receive_json()
            assert data["type"] == "connected"
            assert "session_id" in data
