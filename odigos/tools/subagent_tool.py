from __future__ import annotations

from typing import TYPE_CHECKING

from odigos.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from odigos.core.subagent import SubagentManager


class SpawnSubagentTool(BaseTool):
    """Tool that spawns a background subagent to handle a delegated task."""

    name = "spawn_subagent"
    description = (
        "Delegate a task to a background subagent. The subagent will work "
        "independently and report results when done. Use this for tasks that "
        "would take many tool calls and don't need to block the current conversation."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "instruction": {
                "type": "string",
                "description": "Clear instruction describing what the subagent should do.",
            },
            "timeout": {
                "type": "integer",
                "description": "Max seconds for the subagent to run (default: 600).",
            },
        },
        "required": ["instruction"],
    }

    def __init__(self, subagent_manager: SubagentManager) -> None:
        self._manager = subagent_manager

    async def execute(self, params: dict) -> ToolResult:
        instruction = params.get("instruction")
        if not instruction:
            return ToolResult(success=False, data="", error="Missing required parameter: instruction")

        conversation_id = params.get("_conversation_id")
        if not conversation_id:
            return ToolResult(success=False, data="", error="No conversation context available")

        timeout = params.get("timeout", 600)
        if not isinstance(timeout, int) or timeout < 1:
            timeout = 600

        try:
            subagent_id = await self._manager.spawn(
                instruction=instruction,
                parent_conversation_id=conversation_id,
                timeout=timeout,
            )
            return ToolResult(
                success=True,
                data=f"Subagent {subagent_id} spawned. It will work in the background "
                     f"and results will be delivered when ready.",
            )
        except ValueError as e:
            return ToolResult(success=False, data="", error=str(e))
