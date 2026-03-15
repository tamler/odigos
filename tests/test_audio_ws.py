"""Tests for audio WebSocket endpoints."""
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import FastAPI
from starlette.testclient import TestClient


def _make_app(stt_provider=None, tts_provider=None):
    from odigos.api.audio import router
    app = FastAPI()
    app.include_router(router)
    app.state.settings = SimpleNamespace(api_key="test-key")
    plugin_context = MagicMock()
    plugin_context.get_provider.side_effect = lambda name: {
        "stt": stt_provider,
        "tts": tts_provider,
    }.get(name)
    app.state.plugin_context = plugin_context
    return app


class TestTTSWebSocket:
    def test_tts_no_provider_returns_error(self):
        app = _make_app(tts_provider=None)
        client = TestClient(app)
        with client.websocket_connect("/api/ws/audio/speak?token=test-key") as ws:
            ws.send_json({"text": "hello", "voice": "alba"})
            data = ws.receive_json()
            assert data.get("error") is not None

    def test_tts_auth_failure(self):
        app = _make_app(tts_provider=MagicMock())
        client = TestClient(app)
        with client.websocket_connect("/api/ws/audio/speak?token=wrong-key") as ws:
            data = ws.receive_json()
            assert data.get("error") is not None


class TestSTTWebSocket:
    def test_stt_no_provider_returns_error(self):
        app = _make_app(stt_provider=None)
        client = TestClient(app)
        with client.websocket_connect("/api/ws/audio/transcribe?token=test-key") as ws:
            ws.send_bytes(b"\x00" * 100)
            data = ws.receive_json()
            assert data.get("error") is not None

    def test_stt_auth_failure(self):
        app = _make_app(stt_provider=MagicMock())
        client = TestClient(app)
        with client.websocket_connect("/api/ws/audio/transcribe?token=wrong-key") as ws:
            data = ws.receive_json()
            assert data.get("error") is not None
