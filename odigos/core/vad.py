"""Server-side Voice Activity Detection using Silero VAD v6.

Preprocesses audio before Whisper. Detects whether audio contains
human speech. Saves Whisper API calls on silent/noise recordings.
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

_model = None


def load_model():
    """Load Silero VAD model. Call at startup when voice is enabled."""
    global _model
    if _model is not None:
        return _model

    try:
        from silero_vad import load_silero_vad
        _model = load_silero_vad()
        logger.info("Silero VAD model loaded")
        return _model
    except Exception:
        logger.warning("Silero VAD not available — voice will skip speech detection")
        return None


def contains_speech(audio_bytes: bytes, filename: str = "audio.webm") -> bool:
    """Check if audio bytes contain human speech.

    Returns True if speech detected, False if silent/noise only.
    Falls back to True (assume speech) if VAD is unavailable.
    """
    model = load_model()
    if model is None:
        return True

    try:
        from silero_vad import read_audio, get_speech_timestamps

        suffix = Path(filename).suffix or '.webm'
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name

        try:
            wav = read_audio(tmp_path, sampling_rate=16000)
            timestamps = get_speech_timestamps(wav, model, sampling_rate=16000)
            has_speech = len(timestamps) > 0

            if has_speech:
                total_speech_ms = sum(
                    (t['end'] - t['start']) / 16 for t in timestamps
                )
                logger.debug(
                    "VAD: %d speech segments, %.0fms total",
                    len(timestamps), total_speech_ms,
                )
            else:
                logger.debug("VAD: no speech detected")

            return has_speech
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    except Exception:
        logger.debug("VAD check failed", exc_info=True)
        return True  # Fail open
