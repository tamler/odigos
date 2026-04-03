"""Async wrappers for common synchronous file I/O operations.

Use these instead of bare open()/Path.read_text()/yaml.safe_load() inside
async functions to avoid blocking the event loop.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import yaml


async def read_text(path: str | Path) -> str:
    """Read a text file without blocking the event loop."""
    return await asyncio.to_thread(Path(path).read_text)


async def write_text(path: str | Path, content: str) -> None:
    """Write a text file without blocking the event loop."""
    await asyncio.to_thread(Path(path).write_text, content)


async def read_yaml(path: str | Path) -> dict:
    """Read and parse a YAML file without blocking the event loop."""
    def _read():
        with open(path) as f:
            return yaml.safe_load(f) or {}
    return await asyncio.to_thread(_read)


async def write_yaml(path: str | Path, data: dict) -> None:
    """Write a dict to a YAML file without blocking the event loop."""
    def _write():
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False)
    await asyncio.to_thread(_write)


async def append_text(path: str | Path, content: str) -> None:
    """Append text to a file without blocking the event loop."""
    def _append():
        with open(path, "a") as f:
            f.write(content)
    await asyncio.to_thread(_append)


async def write_bytes(path: str | Path, data: bytes) -> None:
    """Write binary data to a file without blocking the event loop."""
    def _write():
        with open(path, "wb") as f:
            f.write(data)
    await asyncio.to_thread(_write)


async def remove_tree(path: str | Path) -> None:
    """Remove a directory tree without blocking the event loop."""
    import shutil
    await asyncio.to_thread(shutil.rmtree, str(path))
