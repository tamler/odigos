"""TTS provider abstraction."""
from __future__ import annotations

import logging
import os
import tempfile
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class TTSProvider(ABC):
    """Base class for text-to-speech providers."""

    name: str = "base"

    @abstractmethod
    async def synthesize(self, text: str) -> bytes:
        """Synthesize text to audio bytes (MP3)."""
        ...


class EdgeTTS(TTSProvider):
    """Edge-TTS cloud provider."""

    name = "edge"

    def __init__(self, voice: str = "en-US-AriaNeural"):
        self._voice = voice

    async def synthesize(self, text: str) -> bytes:
        import edge_tts

        communicate = edge_tts.Communicate(
            text, voice=self._voice
        )
        audio_data = bytearray()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data.extend(chunk["data"])
        logger.info(
            "TTS: synthesized %d bytes via edge-tts (%s)",
            len(audio_data),
            self._voice,
        )
        return bytes(audio_data)


class LocalTTS(TTSProvider):
    """Local Pocket-TTS provider."""

    name = "local"

    def __init__(self, voice: str = "alba"):
        self._voice = voice
        self._provider = None

    async def synthesize(self, text: str) -> bytes:
        if self._provider is None:
            from plugins.tts.provider import PocketTTSProvider

            self._provider = PocketTTSProvider(
                default_voice=self._voice
            )
            self._provider.initialize()

        filepath, _ = self._provider.generate_audio(
            text, self._voice
        )
        try:
            with open(filepath, "rb") as f:
                return f.read()
        finally:
            os.unlink(filepath)


class DisabledTTS(TTSProvider):
    """Placeholder when TTS is disabled."""

    name = "disabled"

    async def synthesize(self, text: str) -> bytes:
        raise RuntimeError("TTS is disabled")


def create_tts_provider(
    voice_config,
    tts_config=None,
) -> TTSProvider:
    """Factory function to create the right TTS provider."""
    provider_name = voice_config.tts_provider

    if provider_name == "edge":
        return EdgeTTS(voice=voice_config.tts_voice)
    elif provider_name == "local":
        voice = tts_config.voice if tts_config else "alba"
        return LocalTTS(voice=voice)
    else:
        return DisabledTTS()
