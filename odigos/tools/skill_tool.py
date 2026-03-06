from __future__ import annotations

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

    def __init__(self, skill_registry: SkillRegistry) -> None:
        self._registry = skill_registry
        self.last_activated_name: str | None = None
        self.last_activated_prompt: str | None = None
        self.last_activated_tools: list[str] | None = None

    async def execute(self, params: dict) -> ToolResult:
        # Reset state
        self.last_activated_name = None
        self.last_activated_prompt = None
        self.last_activated_tools = None

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

        self.last_activated_name = skill.name
        self.last_activated_prompt = skill.system_prompt
        self.last_activated_tools = skill.tools

        return ToolResult(
            success=True,
            data=f"Skill '{name}' activated. Follow the instructions that will appear in context.",
        )
