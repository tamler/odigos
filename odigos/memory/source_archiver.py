"""Archive external content as cleaned markdown in data/sources/.

Source files are immutable — the agent reads from them but never modifies them.
Each file has YAML frontmatter with url, title, scraped_at, content_type, sha256.
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_SOURCES_DIR = Path("data/sources")


def _slugify(text: str, max_len: int = 60) -> str:
    """Convert text to a filesystem-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:max_len]


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


async def archive_source(
    content: str,
    title: str,
    url: str | None = None,
    content_type: str = "article",
    sources_dir: Path | None = None,
) -> str | None:
    """Save cleaned markdown to data/sources/. Returns the file path or None if duplicate."""
    base = sources_dir or _SOURCES_DIR
    base.mkdir(parents=True, exist_ok=True)

    sha = _sha256(content)

    # Dedup: check if any existing file has the same hash
    for existing in base.glob("*.md"):
        try:
            header = existing.read_text(encoding="utf-8")[:500]
            if f"sha256: {sha}" in header:
                logger.debug("Source already archived: %s", existing.name)
                return None
        except Exception:
            continue

    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    slug = _slugify(title) if title else _slugify(url or "untitled")
    filename = f"{date}-{slug}.md"
    filepath = base / filename

    # Avoid collision
    counter = 1
    while filepath.exists():
        filepath = base / f"{date}-{slug}-{counter}.md"
        counter += 1

    frontmatter = f"---\nurl: {url or ''}\ntitle: {title}\nscraped_at: {datetime.now(timezone.utc).isoformat()}\ncontent_type: {content_type}\nsha256: {sha}\n---\n\n"
    filepath.write_text(frontmatter + content, encoding="utf-8")
    logger.info("Archived source: %s", filepath.name)
    return str(filepath)
