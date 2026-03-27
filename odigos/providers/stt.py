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

        try:
            logger.info(
                "STT: sending %d bytes (%s) to Groq %s",
                len(audio_bytes),
                suffix,
                self._model,
            )
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

            raw_text = getattr(transcription, "text", "") or ""
            segments = (
                getattr(transcription, "segments", None) or []
            )
            logger.info(
                "STT raw: '%s' (%d segments)",
                raw_text[:200],
                len(segments),
            )

            for i, seg in enumerate(segments):
                logger.info(
                    "STT seg[%d]: text='%s' no_speech=%.2f"
                    " compress=%.1f",
                    i,
                    seg.get("text", "")[:80],
                    seg.get("no_speech_prob", 0),
                    seg.get("compression_ratio", 0),
                )

            # Filter segments by no_speech_prob
            if segments:
                clean = []
                for seg in segments:
                    if seg.get("no_speech_prob", 0) > 0.9:
                        continue
                    text = seg.get("text", "").strip()
                    if text:
                        clean.append(text)
                result = " ".join(clean).strip()
            else:
                result = raw_text.strip()

            # Drop known hallucination phrases when confidence
            # is low
            _HALLUCINATIONS = {
                "thank you.",
                "thanks for watching.",
                "please subscribe.",
            }
            if result.lower() in _HALLUCINATIONS:
                avg_no_speech = sum(
                    s.get("no_speech_prob", 0) for s in segments
                ) / max(len(segments), 1)
                if avg_no_speech > 0.5:
                    logger.info(
                        "STT: dropping likely hallucination"
                        " '%s' (avg_no_speech=%.2f)",
                        result,
                        avg_no_speech,
                    )
                    result = ""

            logger.info(
                "STT result: '%s'",
                result[:200] if result else "(empty)",
            )
            return result
        finally:
            os.unlink(temp_path)


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
