"""Tests for STT provider abstraction."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from odigos.providers.stt import (
    DisabledSTT,
    GroqSTT,
    LocalSTT,
    create_stt_provider,
)


def _voice(stt_provider="groq", groq_model="whisper-large-v3-turbo"):
    return SimpleNamespace(
        stt_provider=stt_provider,
        groq_model=groq_model,
    )


def _stt(model="small", language="en"):
    return SimpleNamespace(model=model, language=language)


def test_create_groq_provider():
    provider = create_stt_provider(
        voice_config=_voice("groq"),
        groq_api_key="sk-test-key",
    )
    assert isinstance(provider, GroqSTT)
    assert provider.name == "groq"
    assert provider._api_key == "sk-test-key"
    assert provider._model == "whisper-large-v3-turbo"


def test_create_groq_no_key_falls_back():
    provider = create_stt_provider(
        voice_config=_voice("groq"),
        groq_api_key="",
    )
    assert isinstance(provider, DisabledSTT)
    assert provider.name == "disabled"


def test_create_local_provider():
    provider = create_stt_provider(
        voice_config=_voice("local"),
        stt_config=_stt("base", "fr"),
    )
    assert isinstance(provider, LocalSTT)
    assert provider.name == "local"
    assert provider._model_size == "base"
    assert provider._language == "fr"


def test_create_disabled_provider():
    provider = create_stt_provider(
        voice_config=_voice("disabled"),
    )
    assert isinstance(provider, DisabledSTT)


def test_disabled_raises():
    provider = DisabledSTT()
    with pytest.raises(RuntimeError, match="STT is disabled"):
        import asyncio

        asyncio.run(provider.transcribe(b"fake-audio"))


def test_factory_default():
    provider = create_stt_provider(
        voice_config=_voice("whisper-cpp"),
    )
    assert isinstance(provider, DisabledSTT)
