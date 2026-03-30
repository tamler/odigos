"""Server-side Voice Activity Detection using WebRTC VAD.

Uses Google's webrtcvad (C library, no ML deps) to check if audio
contains human speech before sending to Whisper. Converts audio to
PCM via ffmpeg, then runs VAD frame-by-frame.

Zero torch. Zero CUDA. Zero model downloads. Just works.
"""
from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

_vad = None


def load_model():
    """Initialize WebRTC VAD. Call at startup."""
    global _vad
    try:
        import webrtcvad
        _vad = webrtcvad.Vad(2)  # Aggressiveness 0-3 (2 = balanced)
        logger.info("WebRTC VAD initialized (aggressiveness=2)")
        return _vad
    except Exception:
        logger.warning("WebRTC VAD not available")
        return None


def contains_speech(audio_bytes: bytes, filename: str = "audio.webm") -> bool:
    """Check if audio contains human speech.

    Converts audio to 16kHz mono PCM via ffmpeg, then runs WebRTC VAD
    on 30ms frames. If >10% of frames contain speech, returns True.
    """
    if _vad is None:
        return True  # No VAD, assume speech

    try:
        # Write audio to temp file
        suffix = Path(filename).suffix or '.webm'
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(audio_bytes)
            tmp_in = f.name

        # Convert to 16kHz mono 16-bit PCM via ffmpeg
        tmp_out = tmp_in + '.pcm'
        try:
            result = subprocess.run(
                ['ffmpeg', '-y', '-i', tmp_in, '-ar', '16000', '-ac', '1',
                 '-f', 's16le', '-acodec', 'pcm_s16le', tmp_out],
                capture_output=True, timeout=10,
            )
            if result.returncode != 0:
                logger.debug("ffmpeg conversion failed: %s", result.stderr[:200])
                return True  # Can't convert, assume speech

            pcm_data = Path(tmp_out).read_bytes()
        finally:
            Path(tmp_in).unlink(missing_ok=True)
            Path(tmp_out).unlink(missing_ok=True)

        if len(pcm_data) < 960:  # Less than 30ms at 16kHz
            return False

        # Run VAD on 30ms frames (960 bytes = 480 samples * 2 bytes)
        frame_size = 960  # 30ms at 16kHz, 16-bit
        speech_frames = 0
        total_frames = 0

        for i in range(0, len(pcm_data) - frame_size, frame_size):
            frame = pcm_data[i:i + frame_size]
            total_frames += 1
            if _vad.is_speech(frame, 16000):
                speech_frames += 1

        if total_frames == 0:
            return False

        speech_ratio = speech_frames / total_frames
        has_speech = speech_ratio > 0.1  # >10% of frames have speech

        logger.debug(
            "VAD: %d/%d frames have speech (%.0f%%) -> %s",
            speech_frames, total_frames, speech_ratio * 100,
            "SPEECH" if has_speech else "SILENCE",
        )

        return has_speech

    except Exception:
        logger.debug("VAD check failed", exc_info=True)
        return True  # Fail open
