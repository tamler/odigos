"""Tests for the transcribe_audio tool."""
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_transcribe_returns_transcript():
    from odigos.tools.transcribe import TranscribeAudioTool
    mock_stt = MagicMock()
    mock_stt.transcribe_file.return_value = "Hello world this is a test"
    tool = TranscribeAudioTool(stt_provider=mock_stt)
    result = await tool.execute({"source": "/tmp/test.wav"})
    assert result.success is True
    assert "Hello world this is a test" in result.data


@pytest.mark.asyncio
async def test_transcribe_missing_source():
    from odigos.tools.transcribe import TranscribeAudioTool
    tool = TranscribeAudioTool(stt_provider=MagicMock())
    result = await tool.execute({})
    assert result.success is False
    assert "source" in result.error.lower()


@pytest.mark.asyncio
async def test_transcribe_ingests_into_memory():
    from odigos.tools.transcribe import TranscribeAudioTool
    mock_stt = MagicMock()
    mock_stt.transcribe_file.return_value = "Meeting notes about Q3"
    mock_ingester = AsyncMock()
    mock_ingester.ingest.return_value = "doc-123"
    tool = TranscribeAudioTool(stt_provider=mock_stt, ingester=mock_ingester)
    result = await tool.execute({"source": "/tmp/meeting.wav"})
    assert result.success is True
    mock_ingester.ingest.assert_called_once()
    assert "meeting.wav" in mock_ingester.ingest.call_args[1]["filename"]


@pytest.mark.asyncio
async def test_transcribe_handles_provider_error():
    from odigos.tools.transcribe import TranscribeAudioTool
    mock_stt = MagicMock()
    mock_stt.transcribe_file.side_effect = RuntimeError("Model not loaded")
    tool = TranscribeAudioTool(stt_provider=mock_stt)
    result = await tool.execute({"source": "/tmp/test.wav"})
    assert result.success is False
    assert "Model not loaded" in result.error
