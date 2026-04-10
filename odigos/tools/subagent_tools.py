"""Orchestration tools: dispatch, query, cancel sub-agents."""
from __future__ import annotations

import json
import logging

from odigos.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class RunSubagentTool(BaseTool):
    name = "run_subagent"
    category = "orchestration"
    description = (
        "Dispatch a specialized sub-agent to handle a scoped task. "
        "Use for research, heavy analysis, content generation, or any task "
        "that benefits from a fresh context and specialized tools. "
        "Runs asynchronously by default — responds immediately with a task_id "
        "and the result is delivered via notification when complete."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "What the sub-agent should do"},
            "persona": {
                "type": "string",
                "description": "Persona: researcher, coder, editor, analyst, summarizer",
            },
            "skill": {"type": "string", "description": "Optional skill name to use"},
            "context_facts": {
                "type": "array",
                "items": {"type": "string"},
                "description": "User facts to pass to the sub-agent",
            },
            "memory_refs": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Memory queries resolved at execution time for fresh facts",
            },
            "input_artifact": {"type": "string"},
            "on_complete": {"type": "object"},
            "on_failure": {"type": "object"},
            "concurrency_key": {"type": "string"},
        },
        "required": ["task", "persona"],
    }

    def __init__(self, db=None) -> None:
        self._db = db

    async def execute(self, params: dict) -> ToolResult:
        from odigos.core.subagent import run_subagent

        try:
            dispatch = await run_subagent(
                task=params["task"],
                persona=params.get("persona"),
                skill=params.get("skill"),
                context_facts=params.get("context_facts"),
                memory_refs=params.get("memory_refs"),
                input_artifact=params.get("input_artifact"),
                on_complete=params.get("on_complete"),
                on_failure=params.get("on_failure"),
                concurrency_key=params.get("concurrency_key"),
                wait_for_result=False,
                db=self._db,
            )
            return ToolResult(
                success=True,
                data=f"Dispatched sub-agent task: task_id={dispatch.task_id} status={dispatch.status}",
            )
        except ValueError as exc:
            return ToolResult(success=False, data="", error=str(exc))
        except Exception as exc:
            logger.exception("run_subagent tool failed")
            return ToolResult(success=False, data="", error=str(exc))


class RunParallelSubagentsTool(BaseTool):
    name = "run_parallel_subagents"
    category = "orchestration"
    description = (
        "Dispatch multiple sub-agents in parallel. Each runs independently "
        "with its own fresh context. All dispatched asynchronously."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string"},
                        "persona": {"type": "string"},
                        "context_facts": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["task", "persona"],
                },
            },
        },
        "required": ["tasks"],
    }

    def __init__(self, db=None) -> None:
        self._db = db

    async def execute(self, params: dict) -> ToolResult:
        from odigos.core.subagent import run_subagent

        task_ids: list[str] = []
        errors: list[str] = []
        for item in params.get("tasks", []):
            try:
                dispatch = await run_subagent(
                    task=item["task"],
                    persona=item.get("persona"),
                    context_facts=item.get("context_facts"),
                    wait_for_result=False,
                    db=self._db,
                )
                task_ids.append(dispatch.task_id)
            except Exception as exc:
                errors.append(f"{item.get('persona')}: {exc}")

        if not task_ids:
            return ToolResult(
                success=False, data="", error="All dispatches failed: " + "; ".join(errors),
            )
        msg = f"Dispatched {len(task_ids)} sub-agent task(s): {', '.join(t[:8] for t in task_ids)}"
        if errors:
            msg += f" ({len(errors)} failed: {'; '.join(errors)})"
        return ToolResult(success=True, data=msg)


class SubagentStatusTool(BaseTool):
    name = "subagent_status"
    category = "orchestration"
    description = (
        "Check the status of a dispatched sub-agent task by task_id. "
        "Optionally include the tool-call trace (intermediate steps)."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string"},
            "include_trace": {"type": "boolean", "default": False},
        },
        "required": ["task_id"],
    }

    def __init__(self, db=None) -> None:
        self._db = db

    async def execute(self, params: dict) -> ToolResult:
        task_id = params.get("task_id")
        if not task_id:
            return ToolResult(success=False, data="", error="task_id is required")

        row = await self._db.fetch_one(
            "SELECT * FROM tasks WHERE id = ? AND type = 'subagent'",
            (task_id,),
        )
        if not row:
            return ToolResult(success=False, data="", error=f"Task {task_id} not found")

        result_text = ""
        if row["result_json"]:
            try:
                result_obj = json.loads(row["result_json"])
                result_text = result_obj.get("result", "")
            except Exception:
                pass

        summary = (
            f"Task: {task_id}\n"
            f"Status: {row['status']}\n"
            f"Persona: {row.get('persona')}\n"
            f"Duration: {row.get('duration_ms')}ms\n"
            f"Cost: ${row.get('cost_usd') or 0:.4f}\n"
        )
        if row.get("error"):
            summary += f"Error: {row['error']}\n"
        if row.get("artifact_path"):
            summary += f"Artifact: {row['artifact_path']}\n"
        if result_text:
            summary += f"\nResult preview: {result_text[:500]}"

        return ToolResult(success=True, data=summary)


class CancelSubagentTool(BaseTool):
    name = "cancel_subagent"
    category = "orchestration"
    description = "Cancel a pending or running sub-agent task."
    parameters_schema = {
        "type": "object",
        "properties": {"task_id": {"type": "string"}},
        "required": ["task_id"],
    }

    def __init__(self, db=None) -> None:
        self._db = db

    async def execute(self, params: dict) -> ToolResult:
        task_id = params.get("task_id")
        if not task_id:
            return ToolResult(success=False, data="", error="task_id is required")

        await self._db.execute(
            "UPDATE tasks SET cancel_requested = 1 WHERE id = ? AND type = 'subagent'",
            (task_id,),
        )
        return ToolResult(
            success=True, data=f"Cancellation requested for task {task_id}",
        )
