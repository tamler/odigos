"""Pocket-TTS text-to-speech provider with file and streaming support."""
from __future__ import annotations

import logging
import os
import time

logger = logging.getLogger(__name__)


class PocketTTSProvider:
    """Local CPU text-to-speech using Pocket-TTS PyTorch model.

    Supports complete file generation and chunked streaming (~200ms first chunk).
    Model and voice states are loaded eagerly at initialize() since loading is slow.
    """

    def __init__(self, default_voice: str = "alba") -> None:
        self._model = None
        self._voice_states: dict = {}
        self._default_voice = default_voice

    def initialize(self) -> None:
        """Load model and default voice state. Call once at startup."""
        from pocket_tts import TTSModel

        self._model = TTSModel.load_model()
        self._voice_states[self._default_voice] = (
            self._model.get_state_for_audio_prompt(self._default_voice)
        )
        logger.info("Pocket-TTS loaded with voice: %s", self._default_voice)

    @property
    def sample_rate(self) -> int:
        """Output audio sample rate."""
        return self._model.sample_rate

    def _get_voice_state(self, voice: str):
        """Get or load a voice state, caching for reuse."""
        if voice not in self._voice_states:
            self._voice_states[voice] = self._model.get_state_for_audio_prompt(voice)
        return self._voice_states[voice]

    def generate_audio(self, text: str, voice: str | None = None) -> tuple[str, int]:
        """Generate complete WAV file from text. Returns (file_path, duration_ms)."""
        import scipy.io.wavfile

        voice = voice or self._default_voice
        voice_state = self._get_voice_state(voice)
        audio = self._model.generate_audio(voice_state, text)

        os.makedirs("data/audio", exist_ok=True)
        filename = f"{int(time.time())}_{os.urandom(4).hex()}.wav"
        filepath = os.path.join("data/audio", filename)
        scipy.io.wavfile.write(filepath, self._model.sample_rate, audio.numpy())

        duration_ms = int(len(audio) / self._model.sample_rate * 1000)
        return filepath, duration_ms

    async def generate_stream(self, text: str, voice: str | None = None):
        """Stream audio generation. Yields raw PCM bytes as produced."""
        voice = voice or self._default_voice
        voice_state = self._get_voice_state(voice)
        for chunk_tensor in self._model.generate_audio_stream(voice_state, text):
            yield chunk_tensor.numpy().tobytes()
