"""Tests for STT and TTS plugin registration."""
from unittest.mock import MagicMock

from odigos.config import Settings, STTConfig, TTSConfig


def _make_ctx(stt_enabled=False, tts_enabled=False):
    settings = Settings(
        stt=STTConfig(enabled=stt_enabled),
        tts=TTSConfig(enabled=tts_enabled),
    )
    ctx = MagicMock()
    ctx.config = {"settings": settings}
    ctx.register_tool = MagicMock()
    ctx.register_provider = MagicMock()
    ctx.service = None
    return ctx


class TestSTTPluginRegistration:
    def test_stt_disabled_returns_available(self):
        from plugins.stt import register
        ctx = _make_ctx(stt_enabled=False)
        result = register(ctx)
        assert result["status"] == "available"
        ctx.register_tool.assert_not_called()

    def test_stt_enabled_without_package_returns_available(self):
        """When moonshine-voice not installed, returns available with install hint."""
        from plugins.stt import register
        ctx = _make_ctx(stt_enabled=True)
        result = register(ctx)
        assert result["status"] == "available"
        assert "moonshine-voice" in result["error_message"]


class TestTTSPluginRegistration:
    def test_tts_disabled_returns_available(self):
        from plugins.tts import register
        ctx = _make_ctx(tts_enabled=False)
        result = register(ctx)
        assert result["status"] == "available"
        ctx.register_tool.assert_not_called()

    def test_tts_enabled_without_package_returns_available(self):
        """When pocket-tts not installed, returns available with install hint."""
        from plugins.tts import register
        ctx = _make_ctx(tts_enabled=True)
        result = register(ctx)
        assert result["status"] == "available"
        assert "pocket-tts" in result["error_message"]
