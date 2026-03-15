"""Tests for audio file detection in upload endpoint."""

import importlib
import sys
import types


def test_audio_extension_detection():
    from odigos.tools.transcribe import AUDIO_EXTENSIONS
    assert ".wav" in AUDIO_EXTENSIONS
    assert ".mp3" in AUDIO_EXTENSIONS
    assert ".ogg" in AUDIO_EXTENSIONS
    assert ".m4a" in AUDIO_EXTENSIONS
    assert ".webm" in AUDIO_EXTENSIONS
    assert ".flac" in AUDIO_EXTENSIONS
    assert ".opus" in AUDIO_EXTENSIONS
    assert ".pdf" not in AUDIO_EXTENSIONS
    assert ".txt" not in AUDIO_EXTENSIONS


def test_is_audio_file():
    # Provide a stub for markitdown so the upload module can be imported
    # even when the real markitdown package is incompatible.
    needs_cleanup = "markitdown" not in sys.modules
    if needs_cleanup or not hasattr(sys.modules.get("markitdown", None), "MarkItDown"):
        stub = types.ModuleType("markitdown")
        stub.MarkItDown = type("MarkItDown", (), {})
        sys.modules["markitdown"] = stub

    # Reload to pick up the stub if the module was previously cached with an error
    if "odigos.providers.markitdown" in sys.modules:
        importlib.reload(sys.modules["odigos.providers.markitdown"])
    if "odigos.api.upload" in sys.modules:
        importlib.reload(sys.modules["odigos.api.upload"])

    from odigos.api.upload import is_audio_file
    assert is_audio_file("recording.wav") is True
    assert is_audio_file("recording.MP3") is True
    assert is_audio_file("voice.ogg") is True
    assert is_audio_file("document.pdf") is False
    assert is_audio_file("notes.txt") is False
    assert is_audio_file("") is False
