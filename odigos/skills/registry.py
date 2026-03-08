from __future__ import annotations

import logging
import re
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
    builtin: bool = False


class SkillRegistry:
    """Loads and stores SKILL.md prompt templates."""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def load_all(self, skills_dir: str) -> None:
        """Load all .md files with valid YAML frontmatter from the directory."""
        self.skills_dir = skills_dir
        path = Path(skills_dir)
        if not path.is_dir():
            logger.warning("Skills directory not found: %s", skills_dir)
            return

        for md_file in sorted(path.glob("*.md")):
            skill = self._parse_skill(md_file)
            if skill:
                skill.builtin = True
                self._skills[skill.name] = skill
                logger.info("Loaded skill: %s", skill.name)

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def list(self) -> list[Skill]:
        return list(self._skills.values())

    def create(
        self,
        name: str,
        description: str,
        system_prompt: str,
        tools: list[str] | None = None,
        complexity: str = "standard",
        skills_dir: str | None = None,
    ) -> Skill:
        """Create a new skill .md file and register it in the live registry."""
        target_dir = skills_dir or getattr(self, "skills_dir", None)
        if not target_dir:
            raise ValueError("skills_dir is required to write skill files")
        skills_dir = target_dir
        self.skills_dir = target_dir

        if not re.match(r"^[a-z0-9][a-z0-9_-]*$", name):
            raise ValueError(
                f"Invalid skill name: {name!r}. "
                "Use lowercase alphanumeric, hyphens, and underscores only."
            )

        meta = {
            "name": name,
            "description": description,
            "tools": tools or [],
            "complexity": complexity,
        }
        content = f"---\n{yaml.dump(meta, default_flow_style=False)}---\n{system_prompt}\n"

        path = Path(skills_dir) / f"{name}.md"
        if not path.resolve().is_relative_to(Path(skills_dir).resolve()):
            raise ValueError("Skill path escapes skills directory")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

        skill = Skill(
            name=name,
            description=description,
            tools=tools or [],
            complexity=complexity,
            system_prompt=system_prompt,
            builtin=False,
        )
        self._skills[name] = skill
        logger.info("Created skill: %s at %s", name, path)
        return skill

    def update(
        self,
        name: str,
        description: str | None = None,
        instructions: str | None = None,
        tools: list[str] | None = None,
        complexity: str | None = None,
    ) -> Skill:
        """Update an existing agent-created skill. Built-in skills cannot be modified."""
        skill = self._skills.get(name)
        if not skill:
            raise ValueError(f"Skill '{name}' not found")
        if skill.builtin:
            raise ValueError(f"Cannot modify built-in skill '{name}'")

        if description is not None:
            skill.description = description
        if instructions is not None:
            skill.system_prompt = instructions
        if tools is not None:
            skill.tools = tools
        if complexity is not None:
            skill.complexity = complexity

        # Rewrite file on disk
        target_dir = getattr(self, "skills_dir", None)
        if not target_dir:
            raise ValueError("skills_dir is required to persist skill updates")
        if target_dir:
            meta = {
                "name": skill.name,
                "description": skill.description,
                "tools": skill.tools,
                "complexity": skill.complexity,
            }
            content = f"---\n{yaml.dump(meta, default_flow_style=False)}---\n{skill.system_prompt}\n"
            path = Path(target_dir) / f"{name}.md"
            path.write_text(content)

        logger.info("Updated skill: %s", name)
        return skill

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
