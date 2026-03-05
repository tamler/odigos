from __future__ import annotations

from typing import TYPE_CHECKING

from odigos.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from odigos.providers.searxng import SearxngProvider


class SearchTool(BaseTool):
    """Web search tool backed by SearXNG."""

    name = "web_search"
    description = "Search the web for current information on any topic."
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query"},
        },
        "required": ["query"],
    }

    def __init__(self, searxng: SearxngProvider) -> None:
        self.searxng = searxng

    async def execute(self, params: dict) -> ToolResult:
        query = params.get("query")
        if not query:
            return ToolResult(success=False, data="", error="Missing required parameter: query")

        results = await self.searxng.search(query)

        if not results:
            return ToolResult(success=True, data="No results found for this search.")

        lines = [f"## Web search results for: {query}\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. **{r.title}**")
            lines.append(f"   {r.url}")
            lines.append(f"   {r.snippet}\n")

        return ToolResult(success=True, data="\n".join(lines))
