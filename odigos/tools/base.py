from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from odigos.tools.gate import ALWAYS, ToolGate


@dataclass
class ToolContract:
    """Execution contract for a tool -- defines retry, budget, and validation rules."""

    max_retries: dict[str, int] = field(default_factory=lambda: {
        "transient": 2,
        "input": 0,
        "permission": 0,
        "unavailable": 0,
        "unknown": 1,
    })
    timeout_seconds: float = 60.0
    max_cost_usd: float = 0.0  # 0 = no per-call limit
    min_result_length: int = 0  # 0 = no minimum
    retry_backoff_base: float = 1.0  # seconds, doubles each retry


@dataclass
class ToolResult:
    success: bool
    data: str
    error: str | None = None
    side_effect: dict | None = None
    failure_category: str | None = None  # transient, input, permission, unavailable, unknown
    status: str | None = None      # forward-compat: "pending", "complete"
    task_id: str | None = None     # forward-compat: for backgroundable tasks


def auto_distill(text: str) -> str:
    """Head-tail with signal extraction for verbose output.

    Used by the executor as a fallback and by CLITool as a default.
    """
    signal_words = {"error", "exception", "fail", "warning", "traceback", "exit"}
    lines = text.splitlines()
    if len(lines) <= 30:
        return text
    head = "\n".join(lines[:15])
    tail = "\n".join(lines[-15:])
    middle_signals = [
        line for line in lines[15:-15]
        if any(w in line.lower() for w in signal_words)
    ]
    mid = "\n".join(middle_signals[:10]) if middle_signals else "[...truncated...]"
    return f"{head}\n\n{mid}\n\n{tail}"


# Tool categories for smart filtering
CATEGORY_SEARCH = "search"         # web search, knowledge lookup, workspace search
CATEGORY_CREATE = "create"         # file creation, image gen, artifacts
CATEGORY_PRODUCTIVITY = "productivity"  # goals, todos, reminders, kanban, plans
CATEGORY_COMMUNICATION = "communication"  # email, notifications
CATEGORY_CODE = "code"             # code execution, sandbox
CATEGORY_MEMORY = "memory"         # remember facts, skills
CATEGORY_ANALYSIS = "analysis"     # document processing, text analysis, transcription
CATEGORY_MEDIA = "media"           # image processing, translation


class BaseTool(ABC):
    name: str
    gate: ToolGate = ALWAYS  # declarative enabling condition; see odigos/tools/gate.py
    description: str
    category: str = ""  # One of the CATEGORY_* constants
    parameters_schema: dict = {"type": "object", "properties": {}}
    contract: ToolContract = ToolContract()

    @abstractmethod
    async def execute(self, params: dict) -> ToolResult:
        """Execute the tool with the given parameters."""
        ...

    def format_for_context(self, result: ToolResult) -> str:
        """Format tool output for the LLM context window.

        Override to summarize verbose output. Default: return data as-is.
        The executor applies auto-distill if this default is used and output
        exceeds 2000 characters.
        """
        return result.data
