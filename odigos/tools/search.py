from __future__ import annotations

from typing import Any, Protocol

from odigos.tools.base import BaseTool, ToolContract, ToolResult

from odigos.providers.search_base import SearchResult


class SearchProvider(Protocol):
    async def search(self, query: str, num_results: int = 5) -> list[SearchResult]: ...


class SearchTool(BaseTool):
    """Web search tool backed by any SearchProvider."""

    name = "web_search"
    description = "Search the web for current information on any topic. Use for recent events, news, or queries needing multiple source perspectives. Do not use when a single authoritative source suffices — prefer lookup_fact for encyclopedic facts or read_page when you have a specific URL."
    category = "search"
    contract = ToolContract(timeout_seconds=30, max_retries={"transient": 3, "input": 0, "permission": 0, "unavailable": 0, "unknown": 1})
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Natural language question or search terms to find on the web"},
        },
        "required": ["query"],
    }

    def __init__(self, provider: Any = None, *, searxng: Any = None) -> None:
        # Accept either `provider` (new style) or `searxng` (legacy compat)
        self._provider = provider or searxng
        # Keep .searxng attribute for any existing code that references it
        self.searxng = self._provider

    async def execute(self, params: dict) -> ToolResult:
        query = params.get("query")
        if not query:
            return ToolResult(success=False, data="", error="Missing required parameter: query")

        if not self._provider:
            return ToolResult(success=False, data="", error="No search provider configured")

        results = await self._provider.search(query)

        if not results:
            return ToolResult(success=True, data="No results found for this search.")

        lines = [f"## Web search results for: {query}\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. **{r.title}**")
            lines.append(f"   {r.url}")
            lines.append(f"   {r.snippet}\n")

        return ToolResult(success=True, data="\n".join(lines))
