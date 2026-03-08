from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from odigos.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from odigos.skills.registry import SkillRegistry

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
        },
        "required": ["name", "description", "instructions"],
    }

    def __init__(self, skill_registry: SkillRegistry) -> None:
        self._registry = skill_registry

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

        try:
            skill = self._registry.create(
                name=name,
                description=description,
                system_prompt=instructions,
                tools=params.get("tools"),
                complexity=params.get("complexity", "standard"),
            )
        except ValueError as e:
            return ToolResult(success=False, data="", error=str(e))

        return ToolResult(
            success=True,
            data=f"Skill '{skill.name}' created and available in the catalog.",
        )


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
        },
        "required": ["name"],
    }

    def __init__(self, skill_registry: SkillRegistry) -> None:
        self._registry = skill_registry

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
            )
        except ValueError as e:
            return ToolResult(success=False, data="", error=str(e))

        return ToolResult(
            success=True,
            data=f"Skill '{skill.name}' updated.",
        )
