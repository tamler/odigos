"""Tool registry with deferred loading via find_tools.

Tools are registered once at startup. Only a small always-loaded set
is included in every LLM call. The LLM discovers additional tools
via find_tools during execution, and the executor dynamically expands
discovered tool schemas in the same turn.
"""
from __future__ import annotations

import logging

from odigos.tools.base import BaseTool

logger = logging.getLogger(__name__)

# find_tools is the ONLY always-loaded tool. Everything else is discovered
# through it. The system prompt instructs the model to call find_tools first.


class ToolRegistry:
    """Tool registry with deferred loading via find_tools."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def list(self) -> list[BaseTool]:
        return list(self._tools.values())

    def tool_definitions(self, **_kwargs) -> list[dict]:
        """Return find_tools only. Everything else is discovered through it."""
        find = self._tools.get("find_tools")
        if not find:
            return []
        return [self._tool_to_def(find)]

    @staticmethod
    def _tool_to_def(tool: BaseTool) -> dict:
        """Convert a BaseTool to an OpenAI-compatible tool definition."""
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters_schema,
            },
        }


