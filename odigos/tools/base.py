from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ToolResult:
    success: bool
    data: str
    error: str | None = None
    side_effect: dict | None = None


class BaseTool(ABC):
    name: str
    description: str
    parameters_schema: dict = {"type": "object", "properties": {}}

    @abstractmethod
    async def execute(self, params: dict) -> ToolResult:
        """Execute the tool with the given parameters."""
        ...
