"""Tests for audio endpoints (Groq STT + edge-tts TTS)."""
from types import SimpleNamespace

from fastapi import FastAPI
from starlette.testclient import TestClient

from odigos.config import VoiceConfig


def _make_app(voice_config=None, groq_api_key=""):
    from odigos.api.audio import router
    app = FastAPI()
    app.include_router(router)
    app.state.settings = SimpleNamespace(
        api_key="test-key",
        session_secret="",
        groq_api_key=groq_api_key,
        voice=voice_config or VoiceConfig(),
    )
    app.state.plugin_context = None
    return app


class TestTTS:
    def test_tts_returns_audio(self):
        """TTS endpoint should return audio bytes (edge-tts)."""
        app = _make_app()
        client = TestClient(app)
        resp = client.get(
            "/api/audio/speak?text=hello",
            headers={"Authorization": "Bearer test-key"},
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "audio/mpeg"

    def test_tts_empty_text(self):
        app = _make_app()
        client = TestClient(app)
        resp = client.get(
            "/api/audio/speak?text=",
            headers={"Authorization": "Bearer test-key"},
        )
        assert resp.status_code == 200


class TestTTSAuth:
    def test_tts_requires_auth(self):
        app = _make_app()
        client = TestClient(app)
        resp = client.get("/api/audio/speak?text=hello")
        assert resp.status_code == 401

    def test_tts_with_auth_works(self):
        app = _make_app()
        client = TestClient(app)
        resp = client.get(
            "/api/audio/speak?text=hello",
            headers={"Authorization": "Bearer test-key"},
        )
        assert resp.status_code == 200

    def test_tts_disabled_returns_404(self):
        app = _make_app(voice_config=VoiceConfig(tts_provider="disabled"))
        client = TestClient(app)
        resp = client.get(
            "/api/audio/speak?text=hello",
            headers={"Authorization": "Bearer test-key"},
        )
        assert resp.status_code == 404


class TestSTTWebSocket:
    def test_stt_disabled_returns_error(self):
        app = _make_app(voice_config=VoiceConfig(stt_provider="disabled"))
        client = TestClient(app)
        with client.websocket_connect("/api/ws/audio/transcribe?token=test-key") as ws:
            data = ws.receive_json()
            assert "disabled" in data.get("error", "").lower()

    def test_stt_auth_failure(self):
        app = _make_app()
        client = TestClient(app)
        with client.websocket_connect("/api/ws/audio/transcribe?token=wrong-key") as ws:
            data = ws.receive_json()
            assert data.get("error") is not None
