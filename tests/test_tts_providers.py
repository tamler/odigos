"""Tests for TTS provider abstraction."""
from types import SimpleNamespace

import pytest

from odigos.providers.tts import (
    DisabledTTS,
    EdgeTTS,
    LocalTTS,
    create_tts_provider,
)


def _voice_config(tts_provider="edge", tts_voice="en-US-AriaNeural"):
    return SimpleNamespace(
        tts_provider=tts_provider,
        tts_voice=tts_voice,
    )


def test_create_edge_provider():
    provider = create_tts_provider(voice_config=_voice_config("edge"))
    assert isinstance(provider, EdgeTTS)
    assert provider.name == "edge"


def test_create_local_provider():
    tts_config = SimpleNamespace(voice="alba")
    provider = create_tts_provider(
        voice_config=_voice_config("local"),
        tts_config=tts_config,
    )
    assert isinstance(provider, LocalTTS)
    assert provider.name == "local"


def test_create_disabled_provider():
    provider = create_tts_provider(
        voice_config=_voice_config("unknown")
    )
    assert isinstance(provider, DisabledTTS)
    assert provider.name == "disabled"


@pytest.mark.asyncio
async def test_disabled_raises():
    provider = DisabledTTS()
    with pytest.raises(RuntimeError, match="TTS is disabled"):
        await provider.synthesize("hello")


def test_factory_disabled_explicit():
    provider = create_tts_provider(
        voice_config=_voice_config("disabled")
    )
    assert isinstance(provider, DisabledTTS)
