"""Load editable prompt files from data/prompts/ with hardcoded fallbacks."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Tuple

_cache: Dict[str, Tuple[float, str]] = {}

_DEFAULT_BASE_DIR = "data/prompts"


def load_prompt(name: str, fallback: str, base_dir: Optional[str] = None) -> str:
    """Load prompt from {base_dir}/{name}. Cached by mtime. Falls back if missing."""
    base = base_dir or _DEFAULT_BASE_DIR
    path = Path(base) / name
    if not path.exists():
        return fallback
    mtime = path.stat().st_mtime
    cache_key = str(path)
    cached = _cache.get(cache_key)
    if cached and cached[0] == mtime:
        return cached[1]
    content = path.read_text().strip()
    _cache[cache_key] = (mtime, content)
    return content
