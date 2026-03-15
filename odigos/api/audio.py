"""WebSocket endpoints for streaming audio (STT and TTS)."""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import struct

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


def _authenticate(websocket: WebSocket) -> bool:
    """Authenticate WebSocket via query param token."""
    settings = websocket.app.state.settings
    token = websocket.query_params.get("token", "")
    if not settings.api_key:
        return False
    return hmac.compare_digest(token, settings.api_key)


@router.websocket("/ws/audio/transcribe")
async def ws_transcribe(websocket: WebSocket):
    """Stream audio chunks for real-time transcription.

    Client -> Server: binary PCM audio chunks (16kHz, mono, 16-bit)
    Server -> Client: {"partial": "text so far", "final": false}
    On stream end: {"partial": "complete text", "final": true}
    """
    await websocket.accept()

    if not _authenticate(websocket):
        await websocket.send_json({"error": "Authentication failed"})
        await websocket.close(code=4003)
        return

    plugin_context = getattr(websocket.app.state, "plugin_context", None)
    stt_provider = plugin_context.get_provider("stt") if plugin_context else None

    if not stt_provider:
        await websocket.send_json({"error": "STT provider not available"})
        await websocket.close(code=4004)
        return

    last_text = ""
    try:
        async def audio_chunks():
            while True:
                try:
                    data = await websocket.receive_bytes()
                    num_samples = len(data) // 2
                    samples = struct.unpack(f"<{num_samples}h", data)
                    float_samples = [s / 32768.0 for s in samples]
                    yield float_samples, 16000
                except WebSocketDisconnect:
                    return

        async for partial_text in stt_provider.transcribe_stream(audio_chunks()):
            last_text = partial_text
            await websocket.send_json({"partial": partial_text, "final": False})

        await websocket.send_json({"partial": last_text, "final": True})

        # Auto-ingest final transcript into memory
        if last_text:
            ingester = None
            if plugin_context:
                service = getattr(websocket.app.state, "agent_service", None)
                ingester = getattr(service, "doc_ingester", None) if service else None
            if ingester:
                try:
                    import hashlib
                    content_hash = hashlib.sha256(last_text.encode()).hexdigest()
                    await ingester.ingest(
                        text=last_text,
                        filename="voice_stream_transcript",
                        content_hash=content_hash,
                    )
                except Exception:
                    logger.warning("STT WebSocket transcript ingestion failed", exc_info=True)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("STT WebSocket error: %s", e, exc_info=True)
        try:
            await websocket.send_json({"error": str(e)})
        except Exception:
            pass


@router.websocket("/ws/audio/speak")
async def ws_speak(websocket: WebSocket):
    """Stream TTS audio generation.

    Client -> Server: {"text": "speak this", "voice": "alba"}
    Server -> Client: binary float32 PCM audio chunks
    Final: {"done": true, "duration_ms": 1234}
    """
    await websocket.accept()

    if not _authenticate(websocket):
        await websocket.send_json({"error": "Authentication failed"})
        await websocket.close(code=4003)
        return

    plugin_context = getattr(websocket.app.state, "plugin_context", None)
    tts_provider = plugin_context.get_provider("tts") if plugin_context else None

    if not tts_provider:
        await websocket.send_json({"error": "TTS provider not available"})
        await websocket.close(code=4004)
        return

    try:
        raw = await websocket.receive_text()
        request = json.loads(raw)
        text = request.get("text", "")
        voice = request.get("voice")

        if not text:
            await websocket.send_json({"error": "No text provided"})
            return

        total_bytes = 0
        async for chunk_bytes in tts_provider.generate_stream(text, voice):
            await websocket.send_bytes(chunk_bytes)
            total_bytes += len(chunk_bytes)

        samples = total_bytes // 4
        duration_ms = int(samples / tts_provider.sample_rate * 1000) if samples > 0 else 0

        await websocket.send_json({"done": True, "duration_ms": duration_ms})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("TTS WebSocket error: %s", e, exc_info=True)
        try:
            await websocket.send_json({"error": str(e)})
        except Exception:
            pass
