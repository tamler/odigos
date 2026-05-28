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

    # Per-audio-minute cost for Groq Whisper (2026-04 pricing).
    # Future: read from ModelConfig.cost_per_unit once capabilities-config lands.
    COST_PER_AUDIO_MINUTE_USD = 0.04

    def __init__(
        self,
        api_key: str,
        model: str = "whisper-large-v3-turbo",
        budget_tracker=None,
    ):
        self._api_key = api_key
        self._model = model
        self._budget_tracker = budget_tracker

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

        try:
            with open(temp_path, "rb") as af:
                transcription = (
                    await client.audio.transcriptions.create(
                        file=(filename, af),
                        model=self._model,
                        language="en",
                        response_format="verbose_json",
                        temperature=0.0,
                    )
                )

            text = getattr(transcription, "text", "") or ""
            duration = getattr(transcription, "duration", 0.0) or 0.0
            await self._record_cost(duration)
            return text.strip()
        finally:
            os.unlink(temp_path)

    async def _record_cost(self, audio_seconds: float) -> None:
        """Record one successful Whisper transcription against the budget cap."""
        if not self._budget_tracker or audio_seconds <= 0:
            return
        cost = (audio_seconds / 60.0) * self.COST_PER_AUDIO_MINUTE_USD
        try:
            await self._budget_tracker.record_tool_cost(
                cost,
                source="whisper",
                tool_name="voice_stt",
                metadata={"audio_seconds": audio_seconds, "model": self._model},
            )
        except Exception as e:
            logger.warning("Failed to record Whisper cost: %s", e)


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
    budget_tracker=None,
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
            budget_tracker=budget_tracker,
        )
    elif provider_name == "local":
        model = stt_config.model if stt_config else "small"
        lang = stt_config.language if stt_config else "en"
        return LocalSTT(model_size=model, language=lang)
    else:
        return DisabledSTT()
