"""Audio endpoints: STT via WebSocket (webrtcvad + Groq Whisper), TTS via edge-tts."""
from __future__ import annotations

import asyncio
import io
import logging
import struct
import tempfile

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from odigos.api.deps import require_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

# VAD configuration
_SAMPLE_RATE = 16000
_FRAME_MS = 30  # webrtcvad requires 10, 20, or 30ms frames
_FRAME_BYTES = _SAMPLE_RATE * 2 * _FRAME_MS // 1000  # 960 bytes per frame (16-bit mono)
_SILENCE_FRAMES_THRESHOLD = 30  # ~900ms of silence before speech end
_MIN_SPEECH_FRAMES = 10  # minimum ~300ms of speech to avoid noise triggers
_VAD_AGGRESSIVENESS = 2  # 0-3, higher = more aggressive filtering


def _authenticate(websocket: WebSocket) -> bool:
    """Authenticate WebSocket via session cookie or query param token."""
    import hmac
    settings = websocket.app.state.settings

    from odigos.api.auth import SESSION_COOKIE, _validate_session
    cookie = websocket.cookies.get(SESSION_COOKIE)
    if cookie and settings.session_secret:
        session = _validate_session(settings.session_secret, cookie)
        if session:
            return True

    token = websocket.query_params.get("token", "")
    if settings.api_key and token:
        return hmac.compare_digest(token.encode(), settings.api_key.encode())

    return False


def _pcm_to_wav(pcm_data: bytes, sample_rate: int = _SAMPLE_RATE) -> bytes:
    """Wrap raw PCM Int16 mono data in a WAV header."""
    data_size = len(pcm_data)
    header = struct.pack(
        '<4sI4s4sIHHIIHH4sI',
        b'RIFF', 36 + data_size, b'WAVE',
        b'fmt ', 16, 1, 1,  # PCM, mono
        sample_rate, sample_rate * 2, 2, 16,  # byte rate, block align, bits
        b'data', data_size,
    )
    return header + pcm_data


@router.websocket("/ws/audio/transcribe")
async def ws_transcribe(websocket: WebSocket):
    """Stream raw PCM audio for VAD-gated transcription.

    Client sends raw Int16 PCM at 16kHz mono as binary WebSocket frames.
    Server runs webrtcvad per frame, buffers speech segments, and
    transcribes via Groq Whisper when speech ends.
    Responds with {"text": "..."} for each speech segment.
    Responds with {"listening": true} when ready.
    Responds with {"speaking": true/false} for VAD state changes.
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

    # Initialize VAD
    try:
        import webrtcvad
        vad = webrtcvad.Vad(_VAD_AGGRESSIVENESS)
    except ImportError:
        await websocket.send_json({"error": "webrtcvad not installed"})
        await websocket.close(code=4005)
        return

    await websocket.send_json({"listening": True})
    logger.info("Audio WebSocket: listening, expecting 16kHz Int16 mono PCM")

    # State for VAD-gated buffering
    speech_buffer = bytearray()
    pcm_buffer = bytearray()  # accumulates incoming data until we have full frames
    silence_count = 0
    speech_count = 0
    is_speaking = False
    total_frames = 0

    try:
        while True:
            try:
                chunk = await asyncio.wait_for(websocket.receive_bytes(), timeout=30.0)
            except asyncio.TimeoutError:
                # Long silence — if we have buffered speech, transcribe it
                if speech_buffer and speech_count >= _MIN_SPEECH_FRAMES:
                    await _transcribe_and_send(websocket, settings, voice_config, bytes(speech_buffer))
                    speech_buffer.clear()
                    speech_count = 0
                break
            except WebSocketDisconnect:
                break

            # Add to PCM buffer and process complete frames
            pcm_buffer.extend(chunk)
            if total_frames == 0:
                # Log first chunk info + audio level
                import array
                samples = array.array('h', chunk)  # Int16
                if samples:
                    peak = max(abs(s) for s in samples)
                    rms = (sum(s*s for s in samples) / len(samples)) ** 0.5
                    logger.info("Audio WebSocket: first chunk %d bytes, %d samples, peak=%d rms=%.0f (max=32767)",
                                len(chunk), len(samples), peak, rms)

            while len(pcm_buffer) >= _FRAME_BYTES:
                total_frames += 1
                frame = bytes(pcm_buffer[:_FRAME_BYTES])
                del pcm_buffer[:_FRAME_BYTES]

                try:
                    speech_detected = vad.is_speech(frame, _SAMPLE_RATE)
                except Exception:
                    continue

                if speech_detected:
                    if not is_speaking:
                        is_speaking = True
                        try:
                            await websocket.send_json({"speaking": True})
                        except Exception:
                            pass
                    speech_buffer.extend(frame)
                    speech_count += 1
                    silence_count = 0
                else:
                    if is_speaking:
                        # Still in speech — buffer silence frames (speaker might pause briefly)
                        speech_buffer.extend(frame)
                        silence_count += 1

                        if silence_count >= _SILENCE_FRAMES_THRESHOLD:
                            # Speech ended — transcribe
                            is_speaking = False
                            try:
                                await websocket.send_json({"speaking": False})
                            except Exception:
                                pass

                            if speech_count >= _MIN_SPEECH_FRAMES:
                                await _transcribe_and_send(
                                    websocket, settings, voice_config, bytes(speech_buffer),
                                )
                            speech_buffer.clear()
                            speech_count = 0
                            silence_count = 0

    except Exception:
        logger.debug("Audio WebSocket error", exc_info=True)

    # Transcribe any remaining buffered speech
    if speech_buffer and speech_count >= _MIN_SPEECH_FRAMES:
        try:
            await _transcribe_and_send(websocket, settings, voice_config, bytes(speech_buffer))
        except Exception:
            pass

    try:
        await websocket.close()
    except Exception:
        pass


async def _transcribe_and_send(
    websocket: WebSocket, settings, voice_config, pcm_data: bytes,
) -> None:
    """Convert PCM to WAV, send to Groq, return transcription via WebSocket."""
    try:
        await websocket.send_json({"transcribing": True})
    except Exception:
        pass

    text = ""
    try:
        if voice_config.stt_provider == "groq":
            wav_data = _pcm_to_wav(pcm_data)
            text = await _transcribe_groq(settings.groq_api_key, wav_data, voice_config.groq_model)
        elif voice_config.stt_provider == "local":
            plugin_context = getattr(websocket.app.state, "plugin_context", None)
            stt_provider = plugin_context.get_provider("stt") if plugin_context else None
            if stt_provider:
                text = await asyncio.to_thread(stt_provider.transcribe_file_bytes, pcm_data)
    except Exception as e:
        logger.warning("Transcription failed: %s", e)

    try:
        await websocket.send_json({"text": text, "transcribing": False})
    except Exception:
        pass


async def _transcribe_groq(api_key: str, wav_data: bytes, model: str) -> str:
    """Transcribe WAV audio using Groq Whisper API."""
    if not api_key:
        raise ValueError("groq_api_key not configured")

    from groq import AsyncGroq
    client = AsyncGroq(api_key=api_key)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(wav_data)
        f.flush()
        temp_path = f.name

    try:
        logger.info("Transcribing %d bytes of WAV via Groq %s", len(wav_data), model)
        with open(temp_path, "rb") as audio_file:
            transcription = await client.audio.transcriptions.create(
                file=("audio.wav", audio_file),
                model=model,
                language="en",
                response_format="verbose_json",
                temperature=0.0,
            )

        # Filter hallucinations
        segments = getattr(transcription, 'segments', None) or []
        clean_parts = []
        _HALLUCINATION_PHRASES = {
            "thank you", "thanks for watching", "please subscribe",
            "subtitles by", "amara.org", "thanks for listening",
            "you", "bye",
        }
        for seg in segments:
            no_speech = seg.get("no_speech_prob", 0)
            compression = seg.get("compression_ratio", 0)
            text = seg.get("text", "").strip()
            if no_speech > 0.7:
                continue
            if compression > 2.4:
                continue
            if text.lower().rstrip('.!,') in _HALLUCINATION_PHRASES:
                continue
            if text:
                clean_parts.append(text)

        result = " ".join(clean_parts).strip()
        if not result and hasattr(transcription, 'text'):
            raw = transcription.text.strip()
            if raw.lower().rstrip('.!,') not in _HALLUCINATION_PHRASES:
                result = raw

        logger.info("Transcription: %s", result[:100] if result else "(empty)")
        return result
    finally:
        import os
        os.unlink(temp_path)


# -- TTS --

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
