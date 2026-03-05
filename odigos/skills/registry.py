from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


@dataclass
class Skill:
    name: str
    description: str
    tools: list[str]
    complexity: str
    system_prompt: str


class SkillRegistry:
    """Loads and stores SKILL.md prompt templates."""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def load_all(self, skills_dir: str) -> None:
        """Load all .md files with valid YAML frontmatter from the directory."""
        path = Path(skills_dir)
        if not path.is_dir():
            logger.warning("Skills directory not found: %s", skills_dir)
            return

        for md_file in sorted(path.glob("*.md")):
            skill = self._parse_skill(md_file)
            if skill:
                self._skills[skill.name] = skill
                logger.info("Loaded skill: %s", skill.name)

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def list(self) -> list[Skill]:
        return list(self._skills.values())

    def _parse_skill(self, path: Path) -> Skill | None:
        """Parse a SKILL.md file into a Skill dataclass."""
        text = path.read_text()

        if not text.startswith("---"):
            return None

        parts = text.split("---", 2)
        if len(parts) < 3:
            return None

        try:
            meta = yaml.safe_load(parts[1])
        except yaml.YAMLError:
            logger.warning("Failed to parse YAML frontmatter in %s", path)
            return None

        if not isinstance(meta, dict) or "name" not in meta:
            return None

        system_prompt = parts[2].strip()

        return Skill(
            name=meta["name"],
            description=meta.get("description", ""),
            tools=meta.get("tools", []),
            complexity=meta.get("complexity", "standard"),
            system_prompt=system_prompt,
        )
