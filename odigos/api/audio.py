"""Audio endpoints: STT via Groq Whisper (HTTP POST), TTS via edge-tts."""
from __future__ import annotations

import io
import logging
import os
import tempfile

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from odigos.api.deps import require_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


# -- STT: Speech-to-Text --

@router.post("/audio/transcribe", dependencies=[Depends(require_auth)])
async def transcribe_audio(request: Request):
    """Transcribe an uploaded audio file via Groq Whisper.

    Accepts multipart form with 'audio' file field.
    Returns {"text": "transcribed text"}.
    """
    settings = request.app.state.settings
    voice_config = settings.voice

    if voice_config.stt_provider == "disabled":
        return JSONResponse(status_code=404, content={"detail": "STT is disabled"})

    form = await request.form()
    audio_file = form.get("audio")
    if not audio_file:
        return JSONResponse(status_code=400, content={"detail": "No audio file provided"})

    audio_bytes = await audio_file.read()
    logger.info("STT: received %d bytes, filename=%s", len(audio_bytes), getattr(audio_file, 'filename', '?'))

    if len(audio_bytes) < 1000:
        logger.info("STT: audio too short (%d bytes), skipping", len(audio_bytes))
        return {"text": ""}

    try:
        if voice_config.stt_provider == "groq":
            filename = getattr(audio_file, 'filename', 'audio.webm') or 'audio.webm'
            text = await _transcribe_groq(settings.groq_api_key, audio_bytes, filename, voice_config.groq_model)
            return {"text": text}
        else:
            return {"text": "", "error": f"Unknown STT provider: {voice_config.stt_provider}"}
    except Exception as e:
        logger.error("STT failed: %s", e, exc_info=True)
        return {"text": "", "error": str(e)}


async def _transcribe_groq(api_key: str, audio_bytes: bytes, filename: str, model: str) -> str:
    """Send audio file to Groq Whisper API and return transcription."""
    if not api_key:
        raise ValueError("groq_api_key not configured")

    from groq import AsyncGroq
    client = AsyncGroq(api_key=api_key)

    suffix = os.path.splitext(filename)[1] or '.webm'
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(audio_bytes)
        f.flush()
        temp_path = f.name

    try:
        logger.info("STT: sending %d bytes (%s) to Groq %s", len(audio_bytes), suffix, model)
        with open(temp_path, "rb") as af:
            transcription = await client.audio.transcriptions.create(
                file=(filename, af),
                model=model,
                language="en",
                response_format="verbose_json",
                temperature=0.0,
            )

        # Log full response for debugging
        raw_text = getattr(transcription, 'text', '') or ''
        segments = getattr(transcription, 'segments', None) or []
        logger.info("STT raw: '%s' (%d segments)", raw_text[:200], len(segments))

        for i, seg in enumerate(segments):
            logger.info("STT seg[%d]: text='%s' no_speech=%.2f compress=%.1f",
                        i, seg.get('text', '')[:80],
                        seg.get('no_speech_prob', 0),
                        seg.get('compression_ratio', 0))

        # Minimal hallucination filter — only strip known junk from silent audio
        # Don't over-filter: if the user said something, return it
        if segments:
            clean = []
            for seg in segments:
                # Only skip segments that are almost certainly not speech
                if seg.get('no_speech_prob', 0) > 0.9:
                    continue
                text = seg.get('text', '').strip()
                if text:
                    clean.append(text)
            result = " ".join(clean).strip()
        else:
            result = raw_text.strip()

        # Last resort: if the entire result is a known hallucination phrase AND
        # no_speech_prob was high, drop it
        _HALLUCINATIONS = {"thank you.", "thanks for watching.", "please subscribe."}
        if result.lower() in _HALLUCINATIONS:
            avg_no_speech = sum(s.get('no_speech_prob', 0) for s in segments) / max(len(segments), 1)
            if avg_no_speech > 0.5:
                logger.info("STT: dropping likely hallucination '%s' (avg_no_speech=%.2f)", result, avg_no_speech)
                result = ""

        logger.info("STT result: '%s'", result[:200] if result else "(empty)")
        return result
    finally:
        os.unlink(temp_path)


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
