"""Moonshine speech-to-text provider with file and streaming support."""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile

logger = logging.getLogger(__name__)


class MoonshineSTT:
    """Local CPU speech-to-text using Moonshine ONNX models.

    Supports both file transcription and streaming audio chunks.
    Uses streaming-capable model architectures that handle both modes.
    """

    def __init__(self, model_size: str = "small", language: str = "en") -> None:
        self._transcriber = None
        self._model_size = model_size
        self._language = language

    def _ensure_loaded(self) -> None:
        """Load ONNX model on first use. Model stays resident in memory."""
        if self._transcriber is not None:
            return
        from moonshine_voice.transcriber import Transcriber
        from moonshine_voice.moonshine_api import ModelArch
        from moonshine_voice.utils import get_model_path

        arch_map = {
            "tiny": ModelArch.TINY_STREAMING,
            "small": ModelArch.SMALL_STREAMING,
            "medium": ModelArch.MEDIUM_STREAMING,
        }
        arch = arch_map.get(self._model_size, ModelArch.SMALL_STREAMING)
        model_name = f"{self._model_size}-{self._language}"
        model_path = str(get_model_path(model_name))
        self._transcriber = Transcriber(model_path=model_path, model_arch=arch)
        logger.info("Moonshine STT loaded: %s (%s)", model_name, arch)

    def transcribe_file(self, audio_path: str) -> str:
        """Transcribe an audio file to text. Returns full transcript string."""
        self._ensure_loaded()
        wav_path = self._ensure_wav(audio_path)
        converted = wav_path != audio_path
        try:
            from moonshine_voice.utils import load_wav_file

            audio_data, sample_rate = load_wav_file(wav_path)
            transcript = self._transcriber.transcribe_without_streaming(audio_data, sample_rate)
            return " ".join(line.text for line in transcript.lines)
        finally:
            if converted:
                try:
                    os.unlink(wav_path)
                except OSError:
                    pass

    async def transcribe_stream(self, audio_chunks):
        """Transcribe streaming audio. Yields partial transcript strings.

        Args:
            audio_chunks: async iterator of (audio_data, sample_rate) tuples
        """
        self._ensure_loaded()
        async for chunk_data, _sample_rate in audio_chunks:
            transcript = self._transcriber.transcribe(chunk_data)
            if transcript and transcript.lines:
                yield " ".join(line.text for line in transcript.lines)

    def _ensure_wav(self, path: str) -> str:
        """Convert non-WAV audio to WAV via ffmpeg. Returns WAV path."""
        if path.lower().endswith(".wav"):
            return path
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        wav_path = tmp.name
        tmp.close()
        subprocess.run(
            ["ffmpeg", "-i", path, "-ar", "16000", "-ac", "1", "-f", "wav", wav_path],
            capture_output=True,
            check=True,
        )
        return wav_path
