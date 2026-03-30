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
        "Search for available tools by describing what you need to do. "
        "Returns matching tool names and descriptions. Use when you need "
        "a capability not in your current tool set — for example, "
        "'send an email', 'create a kanban card', or 'generate an image'. "
        "Do not use if the tool you need is already available in this turn."
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
        top = matches[:8]

        if not top:
            return ToolResult(
                success=True,
                data="No matching tools found. Try different search terms.",
            )

        lines = ["## Available tools matching your query:\n"]
        for _, tool in top:
            cat = f" [{tool.category}]" if tool.category else ""
            lines.append(f"**{tool.name}**{cat}: {tool.description[:150]}")

        return ToolResult(success=True, data="\n".join(lines))
