"""Server-side Voice Activity Detection using Silero VAD.

Preprocesses audio before sending to Whisper. Detects whether audio
contains human speech. Saves Whisper API calls (and cost) on silent
or noise-only recordings.
"""
from __future__ import annotations

import io
import logging
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

_model = None
_utils = None


def load_model():
    """Load Silero VAD model. Call at startup."""
    global _model, _utils
    if _model is not None:
        return _model, _utils

    try:
        import torch
        model, utils = torch.hub.load(
            repo_or_dir='snakers4/silero-vad',
            model='silero_vad',
            trust_repo=True,
        )
        _model = model
        _utils = utils
        logger.info("Silero VAD model loaded")
        return model, utils
    except Exception:
        logger.warning("Silero VAD not available — voice will skip speech detection")
        return None, None


def contains_speech(audio_bytes: bytes, filename: str = "audio.webm") -> bool:
    """Check if audio bytes contain human speech.

    Returns True if speech detected, False if silent/noise only.
    Falls back to True (assume speech) if VAD is unavailable.
    """
    try:
        model, utils = load_model()
        if model is None:
            return True  # Can't check, assume speech

        (get_speech_timestamps, _, read_audio, _, _) = utils

        # Write bytes to temp file for read_audio
        suffix = Path(filename).suffix or '.webm'
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name

        try:
            import torch
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
        return True  # Fail open -- assume speech
