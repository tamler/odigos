"""Registry for dynamic, evolvable prompt sections.

PROMPT-CACHE PRIORITY BANDS (brittleness audit §3.8)
----------------------------------------------------
Sections are concatenated into the system prompt in ascending `priority`
order, so `priority` defines the cache prefix. Anthropic/OpenROUTER prompt
caching keys on a stable prefix — inserting a section at an existing priority
shifts every later section and busts the cache for ALL users. To keep the
prefix stable, new sections slot into a reserved band rather than reusing a
neighbor's number:

    0-9    security boilerplate (canary, instruction-hierarchy) — rarely changes
    10     identity (one per agent)
    11-19  behavioral rules (guardrails first, then operational rules)
    20-29  voice + style
    30-49  routing rules + classification heuristics
    50     capabilities (what the agent can do)
    51-99  reserved for future sections

Rules:
  - A new section picks an UNUSED number inside its band. Reusing an existing
    section's priority is a cache bust for every existing user.
  - Intentional cache busts are budgeted: 1 per quarter (see spec §3.8).
    Security fixes override the budget.
  - Tool descriptions, find_tools output format, and skill `tools:` lists
    also live in the cached prefix (the tool-definitions block) — the same
    governance applies to changes there.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


@dataclass
class PromptSection:
    name: str
    content: str
    priority: int = 50
    always_include: bool = True
    max_tokens: int = 0  # 0 = unlimited
    exclude_from_prompt: bool = False


class SectionRegistry:
    """Load prompt sections from markdown files with YAML frontmatter.

    Files are cached by mtime and can be overridden by trial overrides.
    """

    def __init__(self, sections_dir: str) -> None:
        self._dir = Path(sections_dir)
        self._cache: dict[str, tuple[float, PromptSection]] = {}

    def load_all(
        self, overrides: dict[str, str] | None = None
    ) -> list[PromptSection]:
        """Load all sections, applying any trial overrides.

        Returns sections sorted by priority (lowest first).
        """
        if not self._dir.exists():
            return []

        sections: list[PromptSection] = []
        for path in sorted(self._dir.glob("*.md")):
            name = path.stem
            section = self._load_one(path)
            if section is None or section.exclude_from_prompt or not section.always_include:
                continue
            if overrides and name in overrides:
                section = PromptSection(
                    name=section.name,
                    content=overrides[name],
                    priority=section.priority,
                    always_include=section.always_include,
                    max_tokens=section.max_tokens,
                )
            sections.append(section)
        sections.sort(key=lambda s: s.priority)
        return sections

    def _load_one(self, path: Path) -> PromptSection | None:
        """Load a single section file, using cache if mtime unchanged."""
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return None

        cached = self._cache.get(path.name)
        if cached and cached[0] == mtime:
            return cached[1]

        try:
            raw = path.read_text()
        except OSError:
            return None

        frontmatter, content = _parse_frontmatter(raw)
        section = PromptSection(
            name=path.stem,
            content=content.strip(),
            priority=frontmatter.get("priority", 50),
            always_include=frontmatter.get("always_include", True),
            max_tokens=frontmatter.get("max_tokens", 0),
            exclude_from_prompt=frontmatter.get("exclude_from_prompt", False),
        )
        self._cache[path.name] = (mtime, section)
        return section


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split YAML frontmatter from markdown content."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        meta = {}
    return meta, parts[2]
