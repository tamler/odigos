"""DecomposeQueryTool -- break complex requests into structured sub-tasks."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from odigos.core.json_utils import parse_json_response
from odigos.core.prompt_loader import load_prompt
from odigos.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from odigos.providers.base import LLMProvider

logger = logging.getLogger(__name__)

_FALLBACK_PROMPT = (
    'Break this complex request into sequential sub-tasks. '
    'Each sub-task should be independently actionable.\n\n'
    'Request: "{query}"\n\n'
    'Respond ONLY with valid JSON:\n'
    '[\n'
    '  {{"step": 1, "task": "description of first sub-task", "approach": "what tool or method to use"}},\n'
    '  {{"step": 2, "task": "description of second sub-task", "approach": "what tool or method to use"}}\n'
    ']\n\n'
    'Keep it concise. 2-6 sub-tasks. Each task should be a clear, single action.'
)


def format_steps(steps: list[dict]) -> str:
    """Format a list of step dicts into a readable numbered list."""
    lines = []
    for step in steps:
        num = step.get("step", "?")
        task = step.get("task", "")
        approach = step.get("approach", "")
        lines.append(f"{num}. {task}")
        if approach:
            lines.append(f"   Approach: {approach}")
    return "\n".join(lines)


class DecomposeQueryTool(BaseTool):
    """Break a complex question or task into simpler sub-tasks."""

    name = "decompose_query"
    description = (
        "Break a complex question or task into simpler sub-tasks for systematic analysis. "
        "Use when a request has multiple parts, requires step-by-step processing, or "
        "involves cross-referencing multiple sources. Returns a numbered list of sub-tasks "
        "to work through one at a time."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The complex query or task to decompose.",
            },
            "parent_step": {
                "type": "integer",
                "description": "Optional parent step number. When provided, the decomposition creates substeps under this parent step instead of a new top-level plan.",
            },
        },
        "required": ["query"],
    }

    def __init__(self, provider: LLMProvider | None = None) -> None:
        self._provider = provider

    async def execute(self, params: dict) -> ToolResult:
        query = params.get("query", "").strip()
        parent_step = params.get("parent_step")
        if not query:
            return ToolResult(success=False, data="", error="No query provided")

        if self._provider is None:
            return self._single_step_fallback(query)

        try:
            prompt_template = load_prompt("decompose.md", fallback=_FALLBACK_PROMPT)
            prompt = prompt_template.replace("{query}", query)

            response = await self._provider.complete(
                [{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=1024,
            )

            steps = parse_json_response(response.content)
            if not isinstance(steps, list) or not steps:
                return self._single_step_fallback(query)

            formatted = format_steps(steps)

            if parent_step is not None:
                # Create substeps under a parent step
                substeps = [
                    {
                        "step": f"{parent_step}.{i + 1}",
                        "task": s.get("task", ""),
                        "status": "pending",
                        "result": None,
                    }
                    for i, s in enumerate(steps)
                ]
                return ToolResult(
                    success=True,
                    data=formatted,
                    side_effect={"parent_step": parent_step, "substeps": substeps},
                )

            steps_list = [
                {"step": i + 1, "task": s.get("task", ""), "status": "pending", "result": None}
                for i, s in enumerate(steps)
            ]
            return ToolResult(
                success=True,
                data=formatted,
                side_effect={"plan_steps": steps_list},
            )

        except Exception:
            logger.warning("Decomposition failed, returning single-step fallback", exc_info=True)
            return self._single_step_fallback(query)

    @staticmethod
    def _single_step_fallback(query: str) -> ToolResult:
        return ToolResult(
            success=True,
            data=f"1. {query}\n   Approach: Address directly",
        )
