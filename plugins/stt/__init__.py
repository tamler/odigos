"""STT plugin -- speech-to-text via Moonshine (local CPU, ONNX).

Registers the transcribe_audio tool and STT provider when stt.enabled is true.
Requires: pip install moonshine-voice
"""
import logging

logger = logging.getLogger(__name__)


def register(ctx):
    settings = ctx.config.get("settings")
    if not settings or not settings.stt.enabled:
        return {"status": "available", "error_message": "STT not enabled in config"}

    try:
        from moonshine_voice.transcriber import Transcriber  # noqa: F401
    except ImportError:
        return {"status": "available", "error_message": "moonshine-voice package not installed. Run: pip install moonshine-voice"}

    from plugins.stt.provider import MoonshineSTT
    from odigos.tools.transcribe import TranscribeAudioTool

    provider = MoonshineSTT(
        model_size=settings.stt.model,
        language=settings.stt.language,
    )
    ctx.register_provider("stt", provider)

    ingester = getattr(ctx.service, "doc_ingester", None) if ctx.service else None
    tool = TranscribeAudioTool(stt_provider=provider, ingester=ingester)
    ctx.register_tool(tool)
    logger.info("STT plugin loaded (model=%s, lang=%s)", settings.stt.model, settings.stt.language)
