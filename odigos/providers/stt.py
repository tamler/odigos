"""STT provider abstraction."""
from __future__ import annotations

import logging
import os
import tempfile
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class STTProvider(ABC):
    """Base class for speech-to-text providers."""

    name: str = "base"

    @abstractmethod
    async def transcribe(
        self, audio_bytes: bytes, filename: str = "audio.webm"
    ) -> str:
        """Transcribe audio bytes to text."""
        ...


class GroqSTT(STTProvider):
    """Groq Whisper API provider."""

    name = "groq"

    def __init__(
        self, api_key: str, model: str = "whisper-large-v3-turbo"
    ):
        self._api_key = api_key
        self._model = model

    async def transcribe(
        self, audio_bytes: bytes, filename: str = "audio.webm"
    ) -> str:
        from groq import AsyncGroq

        client = AsyncGroq(api_key=self._api_key)

        suffix = os.path.splitext(filename)[1] or ".webm"
        with tempfile.NamedTemporaryFile(
            suffix=suffix, delete=False
        ) as f:
            f.write(audio_bytes)
            f.flush()
            temp_path = f.name

        # Convert to mp3 via ffmpeg — browser webm codecs often rejected by Groq
        import subprocess
        mp3_path = temp_path + ".mp3"
        converted = False
        try:
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", temp_path, "-ar", "16000", "-ac", "1", mp3_path],
                capture_output=True, timeout=10,
            )
            if result.returncode == 0 and os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 100:
                converted = True
                logger.info("STT: converted to mp3 (%d bytes)", os.path.getsize(mp3_path))
            else:
                logger.warning("STT: ffmpeg failed (rc=%d): %s", result.returncode, result.stderr[-200:] if result.stderr else "no stderr")
        except Exception as e:
            logger.warning("STT: ffmpeg error: %s", e)

        send_path = mp3_path if converted else temp_path
        send_name = "recording.mp3" if converted else filename

        try:
            with open(send_path, "rb") as af:
                transcription = (
                    await client.audio.transcriptions.create(
                        file=(send_name, af),
                        model=self._model,
                        language="en",
                        response_format="verbose_json",
                        temperature=0.0,
                    )
                )

            text = getattr(transcription, "text", "") or ""
            return text.strip()
        finally:
            os.unlink(temp_path)
            if os.path.exists(mp3_path):
                os.unlink(mp3_path)


class LocalSTT(STTProvider):
    """Local Moonshine ONNX provider."""

    name = "local"

    def __init__(
        self, model_size: str = "small", language: str = "en"
    ):
        self._model_size = model_size
        self._language = language
        self._provider = None

    async def transcribe(
        self, audio_bytes: bytes, filename: str = "audio.webm"
    ) -> str:
        if self._provider is None:
            from moonshine_onnx import MoonshineOnnxModel

            self._provider = MoonshineOnnxModel(
                model_name=self._model_size
            )

        suffix = os.path.splitext(filename)[1] or ".webm"
        with tempfile.NamedTemporaryFile(
            suffix=suffix, delete=False
        ) as f:
            f.write(audio_bytes)
            f.flush()
            temp_path = f.name

        try:
            tokens = self._provider.generate(temp_path)
            return self._provider.tokenizer.decode(
                tokens[0]
            ).strip()
        finally:
            os.unlink(temp_path)


class DisabledSTT(STTProvider):
    """Placeholder when STT is disabled."""

    name = "disabled"

    async def transcribe(
        self, audio_bytes: bytes, filename: str = "audio.webm"
    ) -> str:
        raise RuntimeError("STT is disabled")


def create_stt_provider(
    voice_config,
    groq_api_key: str = "",
    stt_config=None,
) -> STTProvider:
    """Factory function to create the right STT provider."""
    provider_name = voice_config.stt_provider

    if provider_name == "groq":
        if not groq_api_key:
            logger.warning(
                "Groq STT selected but no API key, disabling"
            )
            return DisabledSTT()
        return GroqSTT(
            api_key=groq_api_key,
            model=voice_config.groq_model,
        )
    elif provider_name == "local":
        model = stt_config.model if stt_config else "small"
        lang = stt_config.language if stt_config else "en"
        return LocalSTT(model_size=model, language=lang)
    else:
        return DisabledSTT()
