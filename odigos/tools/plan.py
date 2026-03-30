"""Plan management tools -- check and update task plans."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from odigos.storage import write_plan_result, read_plan_result
from odigos.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from odigos.db import Database

logger = logging.getLogger(__name__)

RESULT_FILE_THRESHOLD = 500  # chars -- results longer than this get filed


class CheckPlanTool(BaseTool):
    """Check the current task plan for the active conversation."""

    name = "check_plan"
    category = "productivity"
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
            logger.debug("Failed to query plan", exc_info=True)
            return ToolResult(success=False, data="", error="Could not load plan")

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
            result_note = ""
            if s.get("result_file"):
                result_note = f" -- [full result in {s['result_file']}]"
            elif s.get("result"):
                result_note = f" -- {s['result']}"
            lines.append(f"- [{marker}] Step {s['step']}: {s['task']}{result_note}")

            # Display substeps if present
            for sub in s.get("substeps", []):
                sub_status = sub.get("status", "pending")
                sub_marker = "x" if sub_status == "done" else " "
                sub_result = ""
                if sub.get("result_file"):
                    sub_result = f" -- [full result in {sub['result_file']}]"
                elif sub.get("result"):
                    sub_result = f" -- {sub['result']}"
                lines.append(f"    - [{sub_marker}] Step {sub['step']}: {sub['task']}{sub_result}")
                if sub_status == "done":
                    done_count += 1
                else:
                    pending_count += 1

        lines.append(f"\nProgress: {done_count}/{done_count + pending_count} steps complete")
        return ToolResult(success=True, data="\n".join(lines))


class UpdatePlanTool(BaseTool):
    """Mark a plan step as done or add a note."""

    name = "update_plan"
    category = "productivity"
    description = (
        "Update the status of a step in the current task plan. "
        "Mark steps as done when completed, or add result notes."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "step": {
                "type": "string",
                "description": "Step number (e.g., '1', '1.1', '2.3').",
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
        step_raw = params.get("step")
        new_status = params.get("status", "done")
        result_note = params.get("result")

        if not conversation_id or not step_raw:
            return ToolResult(success=False, data="", error="Missing step number or conversation context")

        step_num = str(step_raw)

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

        plan_id = row["id"]
        steps = json.loads(row["steps"])
        updated = False

        def _apply_update(step_dict: dict) -> None:
            step_dict["status"] = new_status
            if result_note:
                if len(result_note) > RESULT_FILE_THRESHOLD:
                    try:
                        path = write_plan_result(plan_id, step_num, result_note)
                        step_dict["result"] = result_note[:200] + "..."
                        step_dict["result_file"] = path
                    except Exception:
                        step_dict["result"] = result_note
                else:
                    step_dict["result"] = result_note

        if "." in step_num:
            parent_num, _ = step_num.split(".", 1)
            for s in steps:
                if str(s["step"]) == parent_num:
                    for sub in s.get("substeps", []):
                        if str(sub["step"]) == step_num:
                            _apply_update(sub)
                            updated = True
                            break
                    break
        else:
            for s in steps:
                if str(s["step"]) == step_num:
                    _apply_update(s)
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
        def _all_steps_done(steps):
            for s in steps:
                if s.get("status") != "done":
                    return False
                substeps = s.get("substeps", [])
                if substeps and not _all_steps_done(substeps):
                    return False
            return True

        all_done = _all_steps_done(steps)
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
