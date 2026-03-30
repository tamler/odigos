"""Audio endpoints: STT + TTS via provider abstractions."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from odigos.api.deps import require_auth
from odigos.providers.stt import DisabledSTT

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


@router.post("/audio/transcribe", dependencies=[Depends(require_auth)])
async def transcribe_audio(request: Request):
    """Transcribe uploaded audio. Accepts multipart form with 'audio' file."""
    provider = request.app.state.stt_provider

    if isinstance(provider, DisabledSTT):
        return JSONResponse(status_code=404, content={"detail": "STT is disabled"})

    form = await request.form()
    audio_file = form.get("audio")
    if not audio_file:
        return JSONResponse(status_code=400, content={"detail": "No audio file provided"})

    audio_bytes = await audio_file.read()
    filename = getattr(audio_file, "filename", "audio.webm") or "audio.webm"

    logger.info("STT: received %d bytes, filename=%s", len(audio_bytes), filename)

    if len(audio_bytes) < 1000:
        return {"text": ""}

    try:
        text = await provider.transcribe(audio_bytes, filename)
        return {"text": text}
    except Exception as e:
        logger.error("STT failed: %s", e, exc_info=True)
        return {"text": "", "error": str(e)}


@router.get("/audio/speak", dependencies=[Depends(require_auth)])
async def speak(text: str, request: Request, voice: str | None = None):
    """Convert text to speech."""
    settings = request.app.state.settings
    voice_config = settings.voice

    if voice_config.tts_provider == "disabled":
        return JSONResponse(status_code=404, content={"detail": "TTS is disabled"})

    tts_voice = voice or voice_config.tts_voice
    logger.info("TTS: using voice %s", tts_voice)

    try:
        import edge_tts
        communicate = edge_tts.Communicate(text, tts_voice)
        audio_chunks = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_chunks.append(chunk["data"])

        if not audio_chunks:
            return JSONResponse(status_code=500, content={"detail": "TTS produced no audio"})

        audio_data = b"".join(audio_chunks)
        return StreamingResponse(
            iter([audio_data]),
            media_type="audio/mpeg",
            headers={"Content-Length": str(len(audio_data))},
        )
    except Exception as e:
        logger.error("TTS failed: %s", e, exc_info=True)
        return JSONResponse(status_code=500, content={"detail": str(e)})
