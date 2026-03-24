"""Tool for suggesting clickable next actions to the user."""

from __future__ import annotations

from typing import TYPE_CHECKING

from odigos.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from odigos.core.goal_store import GoalStore


class SuggestActionsTool(BaseTool):
    name = "suggest_actions"
    description = (
        "Present the user with clickable action buttons for next steps. "
        "Use this when you want to offer the user 2-5 options they can choose from. "
        "Each action should be a short, clear description of what you'll do if they pick it. "
        "The user sees buttons they can tap instead of typing. "
        "They can pick one, multiple, or 'Do all' which creates todos for each action."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "actions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of 2-5 action descriptions the user can choose from",
            },
        },
        "required": ["actions"],
    }

    def __init__(self, goal_store: GoalStore | None = None) -> None:
        self._goal_store = goal_store

    async def execute(self, params: dict) -> ToolResult:
        actions = params.get("actions", [])
        if not actions or len(actions) < 2:
            return ToolResult(success=False, data="", error="Provide at least 2 actions")
        if len(actions) > 5:
            actions = actions[:5]

        return ToolResult(
            success=True,
            data=f"Suggested {len(actions)} actions to the user.",
            side_effect={
                "suggested_actions": actions,
            },
        )
