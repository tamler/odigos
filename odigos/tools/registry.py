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

# Tools always available regardless of classification
ALWAYS_AVAILABLE = {
    "web_search", "remember_fact", "find_tools",
    "decompose_query", "check_plan", "update_plan",
}

# Which categories are relevant to each query classification
CLASSIFICATION_CATEGORIES: dict[str, set[str]] = {
    "simple": {"search", "memory", "create"},
    "standard": {"search", "memory", "create", "productivity", "communication", "media"},
    "document_query": {"search", "memory", "analysis", "create"},
    "complex": set(),  # all tools
    "planning": {"search", "productivity", "create", "code", "analysis"},
}


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

    def tool_definitions(
        self,
        classification: str | None = None,
        routing_rules: dict | None = None,
    ) -> list[dict]:
        """Return OpenAI-compatible tool definitions, filtered by classification.

        If classification and routing_rules are provided, only returns tools
        relevant to that query type. Otherwise returns all tools.
        """
        tools = self._filter_tools(classification, routing_rules)
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters_schema,
                },
            }
            for tool in tools
        ]

    def _filter_tools(
        self,
        classification: str | None,
        routing_rules: dict | None,
    ) -> list[BaseTool]:
        """Filter tools based on routing rules and category relevance."""
        all_tools = list(self._tools.values())

        if not classification:
            return all_tools

        # Check explicit routing rules first (takes precedence)
        if routing_rules:
            route = routing_rules.get(classification, {})
            allowed = route.get("tools", "all")
            if allowed != "all":
                if isinstance(allowed, str):
                    allowed_set = {t.strip() for t in allowed.split(",")}
                else:
                    allowed_set = set(allowed)
                return [t for t in all_tools if t.name in allowed_set]

        # Fall back to category-based filtering
        relevant_categories = CLASSIFICATION_CATEGORIES.get(classification)
        if not relevant_categories:
            return all_tools  # complex or unknown = all tools

        return [
            t for t in all_tools
            if t.name in ALWAYS_AVAILABLE
            or not t.category
            or t.category in relevant_categories
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
