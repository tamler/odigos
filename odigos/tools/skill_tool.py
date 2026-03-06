from __future__ import annotations

import json
from typing import TYPE_CHECKING

from odigos.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from odigos.skills.registry import SkillRegistry


class ActivateSkillTool(BaseTool):
    """Tool that activates a skill by loading its full instructions."""

    name = "activate_skill"
    description = (
        "Load a skill's detailed instructions for the current task. "
        "Call this before starting a task that matches a skill in the catalog. "
        "The skill's instructions will be injected as context."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "The name of the skill to activate (from the skill catalog).",
            },
        },
        "required": ["name"],
    }

    # Structured key in ToolResult.data JSON for executor to detect
    ACTIVATION_KEY = "__skill_activation__"

    def __init__(self, skill_registry: SkillRegistry) -> None:
        self._registry = skill_registry

    async def execute(self, params: dict) -> ToolResult:
        name = params.get("name")
        if not name:
            return ToolResult(success=False, data="", error="Missing required parameter: name")

        skill = self._registry.get(name)
        if not skill:
            available = [s.name for s in self._registry.list()]
            return ToolResult(
                success=False,
                data="",
                error=f"Skill '{name}' not found. Available: {', '.join(available)}",
            )

        # Return skill info as structured JSON — executor extracts it.
        # No mutable instance state, safe for concurrent use.
        payload = json.dumps({
            self.ACTIVATION_KEY: True,
            "skill_name": skill.name,
            "skill_prompt": skill.system_prompt,
            "skill_tools": skill.tools,
            "message": f"Skill '{name}' activated. Follow the instructions that will appear in context.",
        })

        return ToolResult(success=True, data=payload)
