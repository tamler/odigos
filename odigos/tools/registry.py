"""Smart tool registry with classification-aware filtering.

Tools are registered once at startup. The registry provides filtered
tool definitions based on query classification and routing rules,
so simple queries don't get 45 tool schemas in context.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from odigos.tools.base import BaseTool

logger = logging.getLogger(__name__)



@dataclass
class ToolSpec:
    """Declarative tool registration spec."""
    tool_class: type
    kwargs_factory: Callable[[Any], dict | None]  # Returns kwargs or None to skip
    condition: Callable[[Any], bool] | None = None


class ToolRegistry:
    """Smart tool registry with classification-aware filtering."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def list(self) -> list[BaseTool]:
        return list(self._tools.values())

    # Core tools always sent alongside find_tools.
    # These cover the most common user intents so the LLM doesn't need
    # to call find_tools for obvious requests like "search X" or "make a song".
    CORE_TOOLS = {
        "find_tools", "web_search", "create_artifact",
        "generate_image", "generate_music", "remember_fact",
    }

    def tool_definitions(self, **_kwargs) -> list[dict]:
        """Return core tools + find_tools. Everything else discovered on demand."""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters_schema,
                },
            }
            for tool in self._tools.values()
            if tool.name in self.CORE_TOOLS
        ]

    def validate_routing_rules(self, routing_rules: dict) -> list[str]:
        """Validate that routing rules reference tools that actually exist.
        Returns list of warning messages for unknown tool references.
        """
        warnings = []
        tool_names = set(self._tools.keys())
        for classification, route in routing_rules.items():
            allowed = route.get("tools", "all")
            if allowed == "all":
                continue
            if isinstance(allowed, str):
                referenced = {t.strip() for t in allowed.split(",")}
            else:
                referenced = set(allowed)
            unknown = referenced - tool_names
            for name in unknown:
                warnings.append(f"Routing rule [{classification}] references unknown tool '{name}'")
        for w in warnings:
            logger.warning(w)
        return warnings

    def register_from_specs(self, specs: list[ToolSpec], context: Any) -> int:
        """Register tools from a declarative spec list. Returns count registered."""
        count = 0
        for spec in specs:
            if spec.condition and not spec.condition(context):
                continue
            kwargs = spec.kwargs_factory(context)
            if kwargs is None:
                continue
            try:
                tool = spec.tool_class(**kwargs)
                self.register(tool)
                count += 1
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    "Failed to register %s", spec.tool_class.__name__, exc_info=True,
                )
        return count
