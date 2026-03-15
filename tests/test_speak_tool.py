"""Tests for the speak tool."""
import pytest
from unittest.mock import MagicMock


@pytest.mark.asyncio
async def test_speak_generates_audio_file():
    from odigos.tools.speak import SpeakTool
    mock_tts = MagicMock()
    mock_tts.generate_audio.return_value = ("data/audio/123_abc.wav", 2500)
    tool = SpeakTool(tts_provider=mock_tts)
    result = await tool.execute({"text": "Hello world"})
    assert result.success is True
    assert "data/audio/123_abc.wav" in result.data
    assert result.side_effect["audio_path"] == "data/audio/123_abc.wav"
    assert result.side_effect["duration_ms"] == 2500
    mock_tts.generate_audio.assert_called_once_with("Hello world", None)


@pytest.mark.asyncio
async def test_speak_with_voice():
    from odigos.tools.speak import SpeakTool
    mock_tts = MagicMock()
    mock_tts.generate_audio.return_value = ("data/audio/456_def.wav", 1000)
    tool = SpeakTool(tts_provider=mock_tts)
    result = await tool.execute({"text": "Test", "voice": "marius"})
    assert result.success is True
    mock_tts.generate_audio.assert_called_once_with("Test", "marius")


@pytest.mark.asyncio
async def test_speak_missing_text():
    from odigos.tools.speak import SpeakTool
    tool = SpeakTool(tts_provider=MagicMock())
    result = await tool.execute({})
    assert result.success is False
    assert "text" in result.error.lower()


@pytest.mark.asyncio
async def test_speak_handles_provider_error():
    from odigos.tools.speak import SpeakTool
    mock_tts = MagicMock()
    mock_tts.generate_audio.side_effect = RuntimeError("Out of memory")
    tool = SpeakTool(tts_provider=mock_tts)
    result = await tool.execute({"text": "Test"})
    assert result.success is False
    assert "Out of memory" in result.error
