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
    code: str | None = None
    parameters: dict | None = None
    verified: bool = False
    timeout: int = 10
    allow_network: bool = False


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
        code: str | None = None,
        parameters: dict | None = None,
        timeout: int = 10,
        allow_network: bool = False,
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

        existing = self._skills.get(name)
        if existing and existing.builtin:
            raise ValueError(f"Cannot overwrite built-in skill '{name}'")

        code_relative = None
        if code is not None:
            from odigos.skills.code_validator import validate_skill_code

            errors = validate_skill_code(code, parameters or {})
            if errors:
                raise ValueError(f"Code validation failed: {'; '.join(errors)}")

            code_dir = Path(skills_dir) / "code"
            code_dir.mkdir(parents=True, exist_ok=True)
            code_file = code_dir / f"{name}.py"
            code_file.write_text(code)
            code_relative = f"skills/code/{name}.py"

        meta = {
            "name": name,
            "description": description,
            "tools": tools or [],
            "complexity": complexity,
        }
        if code_relative:
            meta["code"] = code_relative
            if parameters:
                meta["parameters"] = parameters
            meta["verified"] = False
            meta["timeout"] = timeout
            meta["allow_network"] = allow_network
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
            code=code_relative,
            parameters=parameters if code_relative else None,
            verified=False,
            timeout=timeout if code_relative else 10,
            allow_network=allow_network if code_relative else False,
        )
        self._skills[name] = skill
        logger.info("Created skill: %s at %s", name, path)
        return skill

    def delete(self, name: str) -> None:
        """Delete an agent-created skill. Built-in skills cannot be deleted."""
        skill = self._skills.get(name)
        if not skill:
            raise ValueError(f"Skill '{name}' not found")
        if skill.builtin:
            raise ValueError(f"Cannot delete built-in skill '{name}'")

        target_dir = getattr(self, "skills_dir", None)
        if target_dir:
            path = Path(target_dir) / f"{name}.md"
            if path.exists():
                path.unlink()

            if skill.code:
                code_path = Path.cwd() / skill.code
                if code_path.exists():
                    code_path.unlink()

        del self._skills[name]
        logger.info("Deleted skill: %s", name)

    def update(
        self,
        name: str,
        description: str | None = None,
        instructions: str | None = None,
        tools: list[str] | None = None,
        complexity: str | None = None,
        code: str | None = None,
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

        if code is not None:
            from odigos.skills.code_validator import validate_skill_code

            errors = validate_skill_code(code, skill.parameters or {})
            if errors:
                raise ValueError(f"Code validation failed: {'; '.join(errors)}")

            target_dir_for_code = getattr(self, "skills_dir", None)
            if target_dir_for_code:
                code_dir = Path(target_dir_for_code) / "code"
                code_dir.mkdir(parents=True, exist_ok=True)
                code_file = code_dir / f"{name}.py"
                code_file.write_text(code)
                skill.code = f"skills/code/{name}.py"

            skill.verified = False

        # Rewrite file on disk
        target_dir = getattr(self, "skills_dir", None)
        if not target_dir:
            raise ValueError("skills_dir is required to persist skill updates")

        meta = {
            "name": skill.name,
            "description": skill.description,
            "tools": skill.tools,
            "complexity": skill.complexity,
        }
        if skill.code:
            meta["code"] = skill.code
            if skill.parameters:
                meta["parameters"] = skill.parameters
            meta["verified"] = skill.verified
            meta["timeout"] = skill.timeout
            meta["allow_network"] = skill.allow_network
        content = f"---\n{yaml.dump(meta, default_flow_style=False)}---\n{skill.system_prompt}\n"
        path = Path(target_dir) / f"{name}.md"
        if not path.resolve().is_relative_to(Path(target_dir).resolve()):
            raise ValueError("Skill path escapes skills directory")
        path.write_text(content)

        logger.info("Updated skill: %s", name)
        return skill

    def register_code_skills(self, tool_registry) -> int:
        """Register CodeSkillRunner tools for all skills that have a code field."""
        from odigos.tools.code_skill_runner import CodeSkillRunner

        count = 0
        for skill in self._skills.values():
            if not skill.code:
                continue

            code_path = Path.cwd() / skill.code
            if not code_path.exists():
                logger.warning(
                    "Code skill '%s' references missing file: %s", skill.name, code_path
                )
                continue

            tool_name = f"skill_{skill.name}"
            if tool_registry.get(tool_name):
                logger.warning(
                    "Code skill '%s' skipped — tool name '%s' already registered",
                    skill.name,
                    tool_name,
                )
                continue

            target_dir = getattr(self, "skills_dir", None)
            md_path = str(Path(target_dir) / f"{skill.name}.md") if target_dir else None

            runner = CodeSkillRunner(
                skill_name=skill.name,
                skill_description=skill.description,
                code_path=str(code_path),
                parameters=skill.parameters or {},
                timeout=skill.timeout,
                allow_network=skill.allow_network,
                skill_md_path=md_path,
                verified=skill.verified,
            )
            tool_registry.register(runner)
            count += 1
            logger.info("Registered code skill tool: %s", tool_name)

        return count

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
            code=meta.get("code"),
            parameters=meta.get("parameters"),
            verified=meta.get("verified", False),
            timeout=meta.get("timeout", 10),
            allow_network=meta.get("allow_network", False),
        )
