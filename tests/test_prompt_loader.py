"""Tests for the shared prompt loader."""
import os
import tempfile
import time

from odigos.core.prompt_loader import load_prompt, _cache


def test_returns_fallback_when_file_missing():
    _cache.clear()
    result = load_prompt("nonexistent.md", "default content")
    assert result == "default content"


def test_reads_file_when_exists():
    _cache.clear()
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "test.md")
        with open(path, "w") as f:
            f.write("  custom content  ")
        result = load_prompt("test.md", "fallback", base_dir=d)
        assert result == "custom content"


def test_caches_by_mtime():
    _cache.clear()
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "cached.md")
        with open(path, "w") as f:
            f.write("version 1")
        result1 = load_prompt("cached.md", "fallback", base_dir=d)
        assert result1 == "version 1"
        result2 = load_prompt("cached.md", "fallback", base_dir=d)
        assert result2 == "version 1"


def test_reloads_on_mtime_change():
    _cache.clear()
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "reload.md")
        with open(path, "w") as f:
            f.write("version 1")
        load_prompt("reload.md", "fallback", base_dir=d)

        time.sleep(0.05)
        with open(path, "w") as f:
            f.write("version 2")

        result = load_prompt("reload.md", "fallback", base_dir=d)
        assert result == "version 2"
