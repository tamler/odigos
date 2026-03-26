"""WebSocket endpoints for streaming audio (STT via Groq Whisper, TTS via edge-tts)."""
from __future__ import annotations

import asyncio
import io
import logging
import tempfile

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from odigos.api.deps import require_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


def _authenticate(websocket: WebSocket) -> bool:
    """Authenticate WebSocket via session cookie or query param token."""
    import hmac
    settings = websocket.app.state.settings

    # Try session cookie first
    from odigos.api.auth import SESSION_COOKIE, _validate_session
    cookie = websocket.cookies.get(SESSION_COOKIE)
    if cookie and settings.session_secret:
        session = _validate_session(settings.session_secret, cookie)
        if session:
            return True

    # Fall back to query param token
    token = websocket.query_params.get("token", "")
    if settings.api_key and token:
        return hmac.compare_digest(token.encode(), settings.api_key.encode())

    return False


@router.websocket("/ws/audio/transcribe")
async def ws_transcribe(websocket: WebSocket):
    """Stream audio for transcription.

    Client sends binary audio chunks.
    Server responds with {"text": "transcribed text"} when complete.
    """
    await websocket.accept()

    if not _authenticate(websocket):
        await websocket.send_json({"error": "Authentication failed"})
        await websocket.close(code=4003)
        return

    settings = websocket.app.state.settings
    voice_config = settings.voice

    if voice_config.stt_provider == "disabled":
        await websocket.send_json({"error": "Speech-to-text is disabled"})
        await websocket.close(code=4004)
        return

    # Collect audio chunks
    audio_data = bytearray()
    try:
        while True:
            try:
                chunk = await asyncio.wait_for(websocket.receive_bytes(), timeout=2.0)
                audio_data.extend(chunk)
            except asyncio.TimeoutError:
                break  # No more audio, transcribe what we have
            except WebSocketDisconnect:
                break
    except Exception:
        pass

    if not audio_data:
        await websocket.send_json({"text": ""})
        try:
            await websocket.close()
        except Exception:
            pass
        return

    # Transcribe
    text = ""
    try:
        if voice_config.stt_provider == "groq":
            text = await _transcribe_groq(settings.groq_api_key, audio_data, voice_config.groq_model)
        elif voice_config.stt_provider == "local":
            # Fall back to local moonshine if configured
            plugin_context = getattr(websocket.app.state, "plugin_context", None)
            stt_provider = plugin_context.get_provider("stt") if plugin_context else None
            if stt_provider:
                text = await asyncio.to_thread(stt_provider.transcribe_file_bytes, bytes(audio_data))
    except Exception as e:
        logger.warning("Transcription failed: %s", e)
        await websocket.send_json({"error": f"Transcription failed: {e}"})
        try:
            await websocket.close()
        except Exception:
            pass
        return

    await websocket.send_json({"text": text})
    try:
        await websocket.close()
    except Exception:
        pass


async def _transcribe_groq(api_key: str, audio_data: bytes, model: str) -> str:
    """Transcribe audio using Groq Whisper API."""
    if not api_key:
        raise ValueError("groq_api_key not configured")

    from groq import AsyncGroq

    client = AsyncGroq(api_key=api_key)

    # Write audio to a temp file (Groq API expects a file)
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
        f.write(audio_data)
        f.flush()
        temp_path = f.name

    try:
        with open(temp_path, "rb") as audio_file:
            transcription = await client.audio.transcriptions.create(
                file=("audio.webm", audio_file),
                model=model,
                response_format="text",
            )
        return transcription.strip() if isinstance(transcription, str) else transcription.text.strip()
    finally:
        import os
        os.unlink(temp_path)


@router.get("/audio/speak", dependencies=[Depends(require_auth)])
async def speak(text: str, request: Request):
    """Convert text to speech using edge-tts. Returns audio stream."""
    settings = request.app.state.settings
    voice_config = settings.voice

    if voice_config.tts_provider == "disabled":
        from fastapi.responses import JSONResponse
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
