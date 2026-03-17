"""Plan management tools -- check and update task plans."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from odigos.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from odigos.db import Database

logger = logging.getLogger(__name__)


class CheckPlanTool(BaseTool):
    """Check the current task plan for the active conversation."""

    name = "check_plan"
    description = (
        "Review the current task plan and see which steps are pending, in progress, "
        "or done. Use periodically when working through a multi-step task to stay "
        "on track and decide what to do next."
    )
    parameters_schema = {
        "type": "object",
        "properties": {},
    }

    def __init__(self, db: Database) -> None:
        self._db = db

    async def execute(self, params: dict) -> ToolResult:
        conversation_id = params.get("_conversation_id", "")
        if not conversation_id:
            return ToolResult(success=False, data="", error="No conversation context")

        try:
            row = await self._db.fetch_one(
                "SELECT steps FROM task_plans WHERE conversation_id = ? "
                "ORDER BY updated_at DESC LIMIT 1",
                (conversation_id,),
            )
        except Exception:
            return ToolResult(success=True, data="No active plan.")

        if not row:
            return ToolResult(success=True, data="No active plan for this conversation.")

        steps = json.loads(row["steps"])
        lines = ["## Current Plan"]
        pending_count = 0
        done_count = 0
        for s in steps:
            status = s.get("status", "pending")
            if status == "done":
                marker = "x"
                done_count += 1
            else:
                marker = " "
                pending_count += 1
            result_note = f" -- {s['result']}" if s.get("result") else ""
            lines.append(f"- [{marker}] Step {s['step']}: {s['task']}{result_note}")

        lines.append(f"\nProgress: {done_count}/{done_count + pending_count} steps complete")
        return ToolResult(success=True, data="\n".join(lines))


class UpdatePlanTool(BaseTool):
    """Mark a plan step as done or add a note."""

    name = "update_plan"
    description = (
        "Update the status of a step in the current task plan. "
        "Mark steps as done when completed, or add result notes."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "step": {
                "type": "integer",
                "description": "The step number to update.",
            },
            "status": {
                "type": "string",
                "enum": ["done", "in_progress", "failed", "pending"],
                "description": "New status for the step.",
            },
            "result": {
                "type": "string",
                "description": "Optional note about the result or finding.",
            },
        },
        "required": ["step", "status"],
    }

    def __init__(self, db: Database) -> None:
        self._db = db

    async def execute(self, params: dict) -> ToolResult:
        conversation_id = params.get("_conversation_id", "")
        step_num = params.get("step")
        new_status = params.get("status", "done")
        result_note = params.get("result")

        if not conversation_id or not step_num:
            return ToolResult(success=False, data="", error="Missing step number or conversation context")

        try:
            row = await self._db.fetch_one(
                "SELECT id, steps FROM task_plans WHERE conversation_id = ? "
                "ORDER BY updated_at DESC LIMIT 1",
                (conversation_id,),
            )
        except Exception:
            return ToolResult(success=False, data="", error="No active plan")

        if not row:
            return ToolResult(success=False, data="", error="No active plan for this conversation")

        steps = json.loads(row["steps"])
        updated = False
        for s in steps:
            if s["step"] == step_num:
                s["status"] = new_status
                if result_note:
                    s["result"] = result_note
                updated = True
                break

        if not updated:
            return ToolResult(success=False, data="", error=f"Step {step_num} not found in plan")

        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "UPDATE task_plans SET steps = ?, updated_at = ? WHERE id = ?",
            (json.dumps(steps), now, row["id"]),
        )

        # Check if plan is complete
        all_done = all(s.get("status") == "done" for s in steps)
        if all_done and self._db:
            try:
                await self._db.execute(
                    "INSERT OR IGNORE INTO plan_outcomes (plan_id, conversation_id, status, created_at) "
                    "VALUES (?, ?, 'pending', ?)",
                    (row["id"], conversation_id, now),
                )
            except Exception:
                pass

        return ToolResult(
            success=True,
            data=f"Step {step_num} updated to '{new_status}'." + (f" Note: {result_note}" if result_note else ""),
        )
