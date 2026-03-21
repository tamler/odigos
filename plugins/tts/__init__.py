"""TTS plugin -- text-to-speech via Pocket-TTS (local CPU, PyTorch).

Registers the speak tool and TTS provider when tts.enabled is true.
Requires: pip install pocket-tts scipy
"""
import logging

logger = logging.getLogger(__name__)


def register(ctx):
    settings = ctx.config.get("settings")
    if not settings or not settings.tts.enabled:
        return {"status": "available", "error_message": "TTS not enabled in config"}

    try:
        from pocket_tts import TTSModel  # noqa: F401
    except ImportError:
        return {"status": "available", "error_message": "pocket-tts package not installed. Run: pip install pocket-tts scipy"}

    from plugins.tts.provider import PocketTTSProvider
    from odigos.tools.speak import SpeakTool

    provider = PocketTTSProvider(default_voice=settings.tts.voice)
    provider.initialize()
    ctx.register_provider("tts", provider)

    tool = SpeakTool(tts_provider=provider)
    ctx.register_tool(tool)
    logger.info("TTS plugin loaded (voice=%s)", settings.tts.voice)
