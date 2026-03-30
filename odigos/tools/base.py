from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


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
    description: str
    category: str = ""  # One of the CATEGORY_* constants
    parameters_schema: dict = {"type": "object", "properties": {}}
    contract: ToolContract = ToolContract()

    @abstractmethod
    async def execute(self, params: dict) -> ToolResult:
        """Execute the tool with the given parameters."""
        ...
