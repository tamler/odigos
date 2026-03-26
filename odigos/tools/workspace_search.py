"""Workspace search tool — find notebooks and kanban boards by name."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from odigos.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from odigos.db import Database

logger = logging.getLogger(__name__)


class WorkspaceSearchTool(BaseTool):
    name = "search_workspace"
    description = (
        "Search for notebooks and kanban boards by name. "
        "Use when the user refers to a workspace item by name "
        '(e.g., "open my journal", "show the roadmap board", "continue the story notebook"). '
        "Returns matching items with their IDs for navigation."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search term (notebook or board name/title)",
            },
            "type": {
                "type": "string",
                "enum": ["notebook", "board", "all"],
                "description": "What to search: notebook, board, or all (default: all)",
            },
        },
        "required": ["query"],
    }

    def __init__(self, db: Database) -> None:
        self.db = db

    async def execute(self, params: dict) -> ToolResult:
        query = params.get("query", "").strip()
        search_type = params.get("type", "all")

        if not query:
            return ToolResult(success=False, data="", error="Query is required")

        results = []
        pattern = f"%{query}%"

        if search_type in ("notebook", "all"):
            notebooks = await self.db.fetch_all(
                "SELECT id, title, updated_at FROM notebooks "
                "WHERE title LIKE ? ORDER BY updated_at DESC LIMIT 5",
                (pattern,),
            )
            for nb in notebooks:
                results.append(
                    f"Notebook: \"{nb['title']}\" (id: {nb['id']}, "
                    f"updated: {nb['updated_at'][:10]}, "
                    f"path: /notebooks/{nb['id']})"
                )

        if search_type in ("board", "all"):
            boards = await self.db.fetch_all(
                "SELECT id, title, updated_at FROM kanban_boards "
                "WHERE title LIKE ? ORDER BY updated_at DESC LIMIT 5",
                (pattern,),
            )
            for b in boards:
                results.append(
                    f"Board: \"{b['title']}\" (id: {b['id']}, "
                    f"updated: {b['updated_at'][:10]}, "
                    f"path: /kanban/{b['id']})"
                )

        if not results:
            return ToolResult(
                success=True,
                data=f"No notebooks or boards found matching \"{query}\".",
            )

        return ToolResult(
            success=True,
            data="\n".join(results),
        )
