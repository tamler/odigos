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

    def tool_definitions(self, **_kwargs) -> list[dict]:
        """Return only the find_tools definition. Everything else is discovered on demand."""
        find = self._tools.get("find_tools")
        if not find:
            return []
        return [{
            "type": "function",
            "function": {
                "name": find.name,
                "description": find.description,
                "parameters": find.parameters_schema,
            },
        }]

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
