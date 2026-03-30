"""Audio endpoints: STT + TTS via provider abstractions."""
from __future__ import annotations

import io
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from odigos.api.deps import require_auth
from odigos.providers.stt import DisabledSTT
from odigos.providers.tts import DisabledTTS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


# -- STT: Speech-to-Text --

@router.post(
    "/audio/transcribe", dependencies=[Depends(require_auth)]
)
async def transcribe_audio(request: Request):
    """Transcribe uploaded audio via the configured STT provider.

    Accepts multipart form with 'audio' file field.
    Returns {"text": "transcribed text"}.
    """
    provider = request.app.state.stt_provider

    if isinstance(provider, DisabledSTT):
        return JSONResponse(
            status_code=404,
            content={"detail": "STT is disabled"},
        )

    form = await request.form()
    audio_file = form.get("audio")
    if not audio_file:
        return JSONResponse(
            status_code=400,
            content={"detail": "No audio file provided"},
        )

    audio_bytes = await audio_file.read()
    filename = (
        getattr(audio_file, "filename", "audio.webm")
        or "audio.webm"
    )
    logger.info(
        "STT: received %d bytes, filename=%s",
        len(audio_bytes),
        filename,
    )

    if len(audio_bytes) < 1000:
        logger.info("STT: audio too short (%d bytes), skipping", len(audio_bytes))
        return {"text": ""}

    # VAD: check for actual human speech before calling Whisper
    try:
        from odigos.core.vad import contains_speech
        import asyncio
        has_speech = await asyncio.to_thread(contains_speech, audio_bytes, filename)
        if not has_speech:
            logger.info("STT: VAD detected no speech, skipping Whisper")
            return {"text": ""}
    except Exception:
        logger.warning("VAD unavailable, sending to Whisper without check")

    try:
        text = await provider.transcribe(audio_bytes, filename)
        return {"text": text}
    except Exception as e:
        logger.error("STT failed: %s", e, exc_info=True)
        return {"text": "", "error": str(e)}


# -- TTS: Text-to-Speech --

@router.get("/audio/speak", dependencies=[Depends(require_auth)])
async def speak(
    text: str,
    request: Request,
    voice: str | None = None,
):
    """Convert text to speech. Optional voice param overrides config."""
    settings = request.app.state.settings
    voice_config = settings.voice

    if voice_config.tts_provider == "disabled":
        return JSONResponse(
            status_code=404,
            content={"detail": "TTS is disabled"},
        )

    if not text:
        return StreamingResponse(
            io.BytesIO(b""), media_type="audio/mpeg"
        )

    try:
        # Use voice from query param, or current settings
        tts_voice = voice or voice_config.tts_voice
        logger.info("TTS: using voice %s", tts_voice)

        if voice_config.tts_provider == "edge":
            import edge_tts
            communicate = edge_tts.Communicate(
                text, voice=tts_voice,
            )
            audio_data = bytearray()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_data.extend(chunk["data"])
            audio_bytes = bytes(audio_data)
        else:
            from odigos.providers.tts import create_tts_provider
            provider = create_tts_provider(voice_config)
            audio_bytes = await provider.synthesize(text)
        return StreamingResponse(
            io.BytesIO(audio_bytes),
            media_type="audio/mpeg",
            headers={"Content-Disposition": "inline"},
        )
    except Exception as e:
        logger.warning("TTS failed: %s", e)
        return StreamingResponse(
            io.BytesIO(b""), media_type="audio/mpeg"
        )
