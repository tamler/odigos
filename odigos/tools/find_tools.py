"""Meta-tool for progressive tool discovery.

Instead of loading all 45+ tools into every LLM context, the agent gets
a small always-available set plus this tool. When it needs a specialized
capability, it searches for it here and the matching tools are dynamically
added to the next turn.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from odigos.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from odigos.tools.registry import ToolRegistry


class FindToolsTool(BaseTool):
    """Search for available tools by description or capability."""

    name = "find_tools"
    category = "memory"
    description = (
        "Search for tools you don't currently see. You have 40+ tools but "
        "only a few are loaded. Call this when you need to do something "
        "and don't have the right tool — e.g., 'generate music', 'send email', "
        "'create image', 'manage kanban'. Returns tool names and descriptions "
        "so you can call the discovered tool."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Natural language description of what you need to do. "
                    "E.g., 'send email', 'manage kanban board', 'generate image', "
                    "'create a quiz', 'translate text'."
                ),
            },
        },
        "required": ["query"],
    }

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    async def execute(self, params: dict) -> ToolResult:
        query = (params.get("query") or "").lower().strip()
        if not query:
            return ToolResult(success=False, data="", error="No search query provided")

        # Broad queries: list all tools grouped by category
        _BROAD_QUERIES = {"all", "everything", "list", "capabilities", "what can you do", "help"}
        if query in _BROAD_QUERIES or any(bq in query for bq in _BROAD_QUERIES):
            return self._list_all_by_category()

        query_words = set(query.split())
        matches = []

        for tool in self._registry.list():
            if tool.name == self.name:
                continue

            # Score by word overlap with name, description, and category
            text = f"{tool.name} {tool.description} {tool.category}".lower()
            text_words = set(text.split())
            overlap = len(query_words & text_words)

            # Boost exact substring matches in name or category
            if query in tool.name or query in (tool.category or ""):
                overlap += 5
            # Boost partial word matches
            for qw in query_words:
                if any(qw in tw for tw in text_words):
                    overlap += 1

            if overlap > 0:
                matches.append((overlap, tool))

        matches.sort(key=lambda x: x[0], reverse=True)
        top = matches[:5]

        if not top:
            return ToolResult(
                success=True,
                data="No matching tools found. Try different search terms.",
            )

        lines = [f"Found {len(top)} tool(s):"]
        for _, tool in top:
            param_names = list(tool.parameters_schema.get("properties", {}).keys())
            params_str = f" (params: {', '.join(param_names)})" if param_names else ""
            cat_str = f" [{tool.category}]" if tool.category else ""
            lines.append(f"- {tool.name}{cat_str}: {tool.description[:100]}{params_str}")

        return ToolResult(success=True, data="\n".join(lines))

    def _list_all_by_category(self) -> ToolResult:
        """List all tools grouped by category."""
        categories: dict[str, list] = {}
        for tool in self._registry.list():
            if tool.name == self.name:
                continue
            cat = tool.category or "other"
            categories.setdefault(cat, []).append(tool)

        lines = [f"All capabilities ({sum(len(v) for v in categories.values())} tools):"]
        for cat in sorted(categories):
            tools = categories[cat]
            tool_names = ", ".join(t.name for t in tools)
            lines.append(f"\n**{cat}**: {tool_names}")

        return ToolResult(success=True, data="\n".join(lines))
