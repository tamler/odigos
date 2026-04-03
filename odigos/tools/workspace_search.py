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
    category = "search"
    description = (
        "Search for notebooks and kanban boards by name or content. "
        "Use when the user refers to a workspace item by name or topic "
        '(e.g., "open my journal", "find my cat lyrics", "the recipe I saved"). '
        "Searches titles first, then entry content. Returns matching items with IDs."
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
        title_matched_nb_ids: set[str] = set()

        if search_type in ("notebook", "all"):
            # Title search first
            notebooks = await self.db.fetch_all(
                "SELECT id, title, updated_at FROM notebooks "
                "WHERE title LIKE ? ORDER BY updated_at DESC LIMIT 5",
                (pattern,),
            )
            for nb in notebooks:
                title_matched_nb_ids.add(nb["id"])
                results.append(
                    f"Notebook: \"{nb['title']}\" (id: {nb['id']}, "
                    f"updated: {nb['updated_at'][:10]}, "
                    f"path: /notebooks/{nb['id']})"
                )

            # Content search for notebooks not already matched by title
            if len(results) < 5:
                remaining = 5 - len(results)
                placeholders = (
                    ",".join("?" for _ in title_matched_nb_ids)
                    if title_matched_nb_ids
                    else "''"
                )
                exclude_ids = list(title_matched_nb_ids) if title_matched_nb_ids else []

                # Split query into words for broader content matching
                words = query.split()
                first_word = words[0] if words else query
                word_conditions = " AND ".join(
                    "e.content LIKE ?" for _ in words
                )
                word_patterns = [f"%{w}%" for w in words]

                content_query = (
                    "SELECT DISTINCT n.id, n.title, n.updated_at, "
                    "SUBSTR(e.content, MAX(1, INSTR(LOWER(e.content), LOWER(?)) - 40), 100)"
                    " AS snippet "
                    "FROM notebook_entries e "
                    "JOIN notebooks n ON n.id = e.notebook_id "
                    f"WHERE ({word_conditions}) AND e.status != 'rejected'"
                )
                query_params: list = [first_word] + word_patterns

                if exclude_ids:
                    content_query += f" AND n.id NOT IN ({placeholders})"
                    query_params.extend(exclude_ids)

                content_query += " ORDER BY e.updated_at DESC LIMIT ?"
                query_params.append(remaining)

                content_matches = await self.db.fetch_all(
                    content_query, tuple(query_params)
                )
                for row in content_matches:
                    snippet = row["snippet"] if isinstance(row, dict) else row[3]
                    title = row["title"] if isinstance(row, dict) else row[1]
                    nb_id = row["id"] if isinstance(row, dict) else row[0]
                    updated = row["updated_at"] if isinstance(row, dict) else row[2]
                    results.append(
                        f"Notebook: \"{title}\" (id: {nb_id}, "
                        f"updated: {updated[:10]}, "
                        f"path: /notebooks/{nb_id})\n"
                        f"  Match: \"...{snippet.strip()}...\""
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
