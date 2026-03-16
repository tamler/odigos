from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from odigos.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from odigos.skills.registry import SkillRegistry
    from odigos.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class CreateSkillTool(BaseTool):
    """Tool that creates a new reusable skill."""

    name = "create_skill"
    description = (
        "Create a new reusable skill with instructions for a specific task type. "
        "Use this when you notice a recurring pattern that would benefit from "
        "standardized instructions. The skill will be immediately available."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Lowercase name with hyphens/underscores (e.g. 'daily-digest').",
            },
            "description": {
                "type": "string",
                "description": "One-line description of what the skill does.",
            },
            "instructions": {
                "type": "string",
                "description": "Full instructions the agent should follow when this skill is activated.",
            },
            "tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of tool names this skill typically uses (optional).",
            },
            "complexity": {
                "type": "string",
                "enum": ["light", "standard", "heavy"],
                "description": "Expected complexity level (default: standard).",
            },
            "code": {
                "type": "string",
                "description": "Python code defining a run() function that returns a string. Makes the skill an executable tool.",
            },
            "parameters": {
                "type": "object",
                "description": "Parameter schema for run(). Keys are param names, values have 'type' and 'description'.",
            },
            "timeout": {
                "type": "integer",
                "description": "Sandbox timeout seconds (default 10, max 60).",
            },
            "allow_network": {
                "type": "boolean",
                "description": "Allow network access (default false).",
            },
        },
        "required": ["name", "description", "instructions"],
    }

    def __init__(self, skill_registry: SkillRegistry, tool_registry: ToolRegistry | None = None) -> None:
        self._registry = skill_registry
        self._tool_registry = tool_registry

    async def execute(self, params: dict) -> ToolResult:
        name = params.get("name")
        description = params.get("description")
        instructions = params.get("instructions")

        if not name or not description or not instructions:
            return ToolResult(
                success=False,
                data="",
                error="Missing required parameters: name, description, and instructions are all required.",
            )

        code = params.get("code")
        parameters = params.get("parameters")
        timeout = params.get("timeout", 10)
        allow_network = params.get("allow_network", False)

        try:
            skill = self._registry.create(
                name=name,
                description=description,
                system_prompt=instructions,
                tools=params.get("tools"),
                complexity=params.get("complexity", "standard"),
                code=code,
                parameters=parameters,
                timeout=timeout,
                allow_network=allow_network,
            )
        except ValueError as e:
            return ToolResult(success=False, data="", error=str(e))

        if code and self._tool_registry:
            from pathlib import Path
            from odigos.tools.code_skill_runner import CodeSkillRunner

            code_path = str(Path.cwd() / skill.code)
            target_dir = getattr(self._registry, "skills_dir", None)
            md_path = str(Path(target_dir) / f"{skill.name}.md") if target_dir else None

            runner = CodeSkillRunner(
                skill_name=skill.name,
                skill_description=skill.description,
                code_path=code_path,
                parameters=skill.parameters or {},
                timeout=skill.timeout,
                allow_network=skill.allow_network,
                skill_md_path=md_path,
                verified=skill.verified,
            )
            self._tool_registry.register(runner)

        msg = f"Skill '{skill.name}' created"
        if code:
            msg += " as an executable code skill tool"
        msg += " and available in the catalog."

        return ToolResult(success=True, data=msg)


class UpdateSkillTool(BaseTool):
    """Tool that updates an existing agent-created skill."""

    name = "update_skill"
    description = (
        "Update an existing skill you created. Use this to refine instructions "
        "based on corrections or learned improvements. Cannot modify built-in skills."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Name of the skill to update.",
            },
            "description": {
                "type": "string",
                "description": "New one-line description (optional).",
            },
            "instructions": {
                "type": "string",
                "description": "New full instructions (optional).",
            },
            "tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": "New list of tool names (optional).",
            },
            "complexity": {
                "type": "string",
                "enum": ["light", "standard", "heavy"],
                "description": "New complexity level (optional).",
            },
            "code": {
                "type": "string",
                "description": "New Python code for an executable code skill (optional).",
            },
        },
        "required": ["name"],
    }

    def __init__(self, skill_registry: SkillRegistry, tool_registry: ToolRegistry | None = None) -> None:
        self._registry = skill_registry
        self._tool_registry = tool_registry

    async def execute(self, params: dict) -> ToolResult:
        name = params.get("name")
        if not name:
            return ToolResult(
                success=False, data="", error="Missing required parameter: name"
            )

        try:
            skill = self._registry.update(
                name=name,
                description=params.get("description"),
                instructions=params.get("instructions"),
                tools=params.get("tools"),
                complexity=params.get("complexity"),
                code=params.get("code"),
            )
        except ValueError as e:
            return ToolResult(success=False, data="", error=str(e))

        if params.get("code") and self._tool_registry and skill.code:
            from pathlib import Path
            from odigos.tools.code_skill_runner import CodeSkillRunner

            tool_name = f"skill_{skill.name}"
            # Remove old runner if present
            old = self._tool_registry.get(tool_name)
            if old:
                self._tool_registry._tools.pop(tool_name, None)

            code_path = str(Path.cwd() / skill.code)
            target_dir = getattr(self._registry, "skills_dir", None)
            md_path = str(Path(target_dir) / f"{skill.name}.md") if target_dir else None

            runner = CodeSkillRunner(
                skill_name=skill.name,
                skill_description=skill.description,
                code_path=code_path,
                parameters=skill.parameters or {},
                timeout=skill.timeout,
                allow_network=skill.allow_network,
                skill_md_path=md_path,
                verified=False,
            )
            self._tool_registry.register(runner)

        return ToolResult(
            success=True,
            data=f"Skill '{skill.name}' updated.",
        )
