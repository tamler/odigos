"""Validation of start_time/end_time args in ProcessAudioTool trim action."""
from __future__ import annotations

import pytest

import odigos.tools.audio_process as audio_mod
from odigos.tools.audio_process import ProcessAudioTool


def _patch_ffmpeg_present(monkeypatch):
    """Make shutil.which report ffmpeg as available regardless of host."""
    monkeypatch.setattr(audio_mod.shutil, "which", lambda _name: "/usr/bin/ffmpeg")


def _patch_input_valid(monkeypatch, tool):
    """Bypass file resolution/validation so we isolate time validation."""
    monkeypatch.setattr(tool, "_resolve_input", lambda p: "/tmp/in.mp3")
    monkeypatch.setattr(tool, "_validate_input", lambda r: None)


@pytest.mark.asyncio
async def test_trim_rejects_ffmpeg_expression(monkeypatch):
    tool = ProcessAudioTool(db=None)
    _patch_ffmpeg_present(monkeypatch)
    _patch_input_valid(monkeypatch, tool)

    # If ffmpeg is reached, the test fails -- validation must short-circuit first.
    async def _boom(*args):
        raise AssertionError("ffmpeg should not be invoked for invalid time")

    monkeypatch.setattr(audio_mod, "_run_ffmpeg", _boom)

    result = await tool.execute(
        {"action": "trim", "input_file": "in.mp3", "start_time": "1*0+0"}
    )
    assert result.success is False
    assert "start_time" in (result.error or "")


@pytest.mark.asyncio
async def test_trim_accepts_valid_times(monkeypatch):
    tool = ProcessAudioTool(db=None)
    _patch_ffmpeg_present(monkeypatch)
    _patch_input_valid(monkeypatch, tool)

    captured = {}

    async def _fake_ffmpeg(*args):
        captured["args"] = args
        return (0, "", "")

    monkeypatch.setattr(audio_mod, "_run_ffmpeg", _fake_ffmpeg)
    monkeypatch.setattr(tool, "_register_artifact", lambda *a, **k: _noop())

    result = await tool.execute(
        {
            "action": "trim",
            "input_file": "in.mp3",
            "start_time": "00:01:30",
            "end_time": "12.5",
        }
    )
    # ffmpeg was reached (validation passed), so failure is not a time-validation error.
    assert "args" in captured
    if not result.success:
        assert "must be seconds" not in (result.error or "")


async def _noop():
    return {}
