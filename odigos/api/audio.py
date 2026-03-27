"""Audio endpoints: STT via provider abstraction, TTS via edge-tts."""
from __future__ import annotations

import io
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from odigos.api.deps import require_auth
from odigos.providers.stt import DisabledSTT

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
        logger.info(
            "STT: audio too short (%d bytes), skipping",
            len(audio_bytes),
        )
        return {"text": ""}

    try:
        text = await provider.transcribe(audio_bytes, filename)
        return {"text": text}
    except Exception as e:
        logger.error("STT failed: %s", e, exc_info=True)
        return {"text": "", "error": str(e)}


# -- TTS: Text-to-Speech --

@router.get("/audio/speak", dependencies=[Depends(require_auth)])
async def speak(text: str, request: Request):
    """Convert text to speech using edge-tts. Returns audio stream."""
    settings = request.app.state.settings
    voice_config = settings.voice

    if voice_config.tts_provider == "disabled":
        return JSONResponse(status_code=404, content={"detail": "TTS is disabled"})

    if not text:
        return StreamingResponse(io.BytesIO(b""), media_type="audio/mpeg")

    try:
        import edge_tts
        communicate = edge_tts.Communicate(text, voice=voice_config.tts_voice)
        audio_data = bytearray()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data.extend(chunk["data"])

        return StreamingResponse(
            io.BytesIO(bytes(audio_data)),
            media_type="audio/mpeg",
            headers={"Content-Disposition": "inline"},
        )
    except Exception as e:
        logger.warning("TTS failed: %s", e)
        return StreamingResponse(io.BytesIO(b""), media_type="audio/mpeg")
