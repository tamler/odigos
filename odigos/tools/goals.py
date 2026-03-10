from __future__ import annotations

from typing import TYPE_CHECKING

from odigos.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from odigos.core.goal_store import GoalStore


class CreateReminderTool(BaseTool):
    name = "create_reminder"
    description = "Set a time-based reminder that fires after a delay. Use for 'remind me', 'don't forget', 'in X hours tell me'."
    parameters_schema = {
        "type": "object",
        "properties": {
            "description": {"type": "string", "description": "What to be reminded about"},
            "due_seconds": {"type": "integer", "description": "Seconds from now until the reminder fires. 0 = immediately."},
            "recurrence": {"type": "string", "description": "Optional: 'daily', 'weekly', 'hourly', 'every Ns' for raw seconds, or natural language like 'every 2 hours', 'every 30 minutes', 'every 3 days'. Omit for one-shot."},
        },
        "required": ["description", "due_seconds"],
    }

    def __init__(self, goal_store: GoalStore) -> None:
        self.goal_store = goal_store

    async def execute(self, params: dict) -> ToolResult:
        description = params.get("description", "")
        due_seconds = int(params.get("due_seconds", 0))
        recurrence = params.get("recurrence")
        conversation_id = params.get("_conversation_id")

        rid = await self.goal_store.create_reminder(
            description=description,
            due_seconds=due_seconds,
            recurrence=recurrence,
            conversation_id=conversation_id,
        )
        return ToolResult(success=True, data=f"Reminder set: {description} (id: {rid[:8]})")


class CreateTodoTool(BaseTool):
    name = "create_todo"
    description = "Create a concrete work item for the agent to complete. Use for 'do X', 'look up Y', 'research Z'."
    parameters_schema = {
        "type": "object",
        "properties": {
            "description": {"type": "string", "description": "What needs to be done"},
            "delay_seconds": {"type": "integer", "description": "Seconds to wait before starting. 0 = do it on next heartbeat tick."},
        },
        "required": ["description"],
    }

    def __init__(self, goal_store: GoalStore) -> None:
        self.goal_store = goal_store

    async def execute(self, params: dict) -> ToolResult:
        description = params.get("description", "")
        delay = int(params.get("delay_seconds", 0))
        conversation_id = params.get("_conversation_id")

        tid = await self.goal_store.create_todo(
            description=description,
            delay_seconds=delay,
            conversation_id=conversation_id,
        )
        return ToolResult(success=True, data=f"Todo created: {description} (id: {tid[:8]})")


class CreateGoalTool(BaseTool):
    name = "create_goal"
    description = "Record a long-term goal or aspiration. Use for 'I want to X', 'my goal is', 'I'm working towards'."
    parameters_schema = {
        "type": "object",
        "properties": {
            "description": {"type": "string", "description": "The goal description"},
        },
        "required": ["description"],
    }

    def __init__(self, goal_store: GoalStore) -> None:
        self.goal_store = goal_store

    async def execute(self, params: dict) -> ToolResult:
        description = params.get("description", "")
        gid = await self.goal_store.create_goal(description=description)
        return ToolResult(success=True, data=f"Goal noted: {description} (id: {gid[:8]})")
