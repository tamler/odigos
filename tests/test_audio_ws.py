"""Tests for audio endpoints (Groq STT + edge-tts TTS)."""
from types import SimpleNamespace

from fastapi import FastAPI
from starlette.testclient import TestClient

from odigos.config import VoiceConfig
from odigos.providers.stt import create_stt_provider
from odigos.providers.tts import create_tts_provider


AUTH = {"Authorization": "Bearer test-key"}


def _make_app(voice_config=None, groq_api_key=""):
    from odigos.api.audio import router
    vc = voice_config or VoiceConfig()
    app = FastAPI()
    app.include_router(router)
    app.state.settings = SimpleNamespace(
        api_key="test-key",
        session_secret="",
        groq_api_key=groq_api_key,
        voice=vc,
    )
    app.state.stt_provider = create_stt_provider(
        voice_config=vc, groq_api_key=groq_api_key,
    )
    app.state.tts_provider = create_tts_provider(
        voice_config=vc,
    )
    app.state.plugin_context = None
    return app


class TestTTS:
    def test_tts_returns_audio(self):
        app = _make_app()
        client = TestClient(app)
        resp = client.get("/api/audio/speak?text=hello", headers=AUTH)
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "audio/mpeg"

    def test_tts_empty_text(self):
        app = _make_app()
        client = TestClient(app)
        resp = client.get("/api/audio/speak?text=", headers=AUTH)
        # Empty text produces no audio chunks, returns 500
        assert resp.status_code == 500

    def test_tts_requires_auth(self):
        app = _make_app()
        client = TestClient(app)
        resp = client.get("/api/audio/speak?text=hello")
        assert resp.status_code == 401

    def test_tts_disabled_returns_404(self):
        app = _make_app(voice_config=VoiceConfig(tts_provider="disabled"))
        client = TestClient(app)
        resp = client.get("/api/audio/speak?text=hello", headers=AUTH)
        assert resp.status_code == 404


class TestSTTTranscribe:
    def test_stt_requires_auth(self):
        app = _make_app()
        client = TestClient(app)
        resp = client.post("/api/audio/transcribe")
        assert resp.status_code == 401

    def test_stt_disabled_returns_404(self):
        app = _make_app(voice_config=VoiceConfig(stt_provider="disabled"))
        client = TestClient(app)
        resp = client.post("/api/audio/transcribe", headers=AUTH)
        assert resp.status_code == 404

    def test_stt_no_file_returns_400(self):
        app = _make_app(groq_api_key="fake-key-for-test")
        client = TestClient(app)
        resp = client.post("/api/audio/transcribe", headers=AUTH)
        assert resp.status_code == 400

    def test_stt_short_audio_returns_empty(self):
        app = _make_app(groq_api_key="fake-key-for-test")
        client = TestClient(app)
        resp = client.post(
            "/api/audio/transcribe",
            headers=AUTH,
            files={"audio": ("test.webm", b"\x00" * 100, "audio/webm")},
        )
        assert resp.status_code == 200
        assert resp.json()["text"] == ""
