from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from odigos.core.resource_store import ResourceStore
from odigos.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from odigos.db import Database


class KanbanListBoardsTool(BaseTool):
    name = "kanban_list_boards"
    category = "productivity"
    description = "List all kanban boards. Use to discover available boards before getting details."
    parameters_schema = {
        "type": "object",
        "properties": {},
    }

    def __init__(self, db: Database) -> None:
        self.db = db

    async def execute(self, params: dict) -> ToolResult:
        try:
            boards = ResourceStore(self.db, "kanban_boards")
            cards = ResourceStore(self.db, "kanban_cards")
            board_list = await boards.list(order_by="created_at ASC")
            if not board_list:
                return ToolResult(success=True, data="No boards found.")
            lines = []
            for board in board_list:
                all_cards = await cards.list(board_id=board["id"])
                count = len(all_cards)
                lines.append(f"- {board['title']} (id: {board['id'][:8]}, cards: {count})")
            return ToolResult(success=True, data="\n".join(lines))
        except Exception as e:
            logger.error("kanban_list_boards failed: %s", e, exc_info=True)
            return ToolResult(success=False, data="", error=str(e))


class KanbanGetBoardTool(BaseTool):
    name = "kanban_get_board"
    category = "productivity"
    description = "Get a kanban board with all columns and cards. Use to see current board state before creating or moving cards."
    parameters_schema = {
        "type": "object",
        "properties": {
            "board_id": {"type": "string", "description": "UUID of the board (from kanban_list_boards)"},
        },
        "required": ["board_id"],
    }

    def __init__(self, db: Database) -> None:
        self.db = db

    async def execute(self, params: dict) -> ToolResult:
        board_id = params.get("board_id", "")
        try:
            boards = ResourceStore(self.db, "kanban_boards")
            cols = ResourceStore(self.db, "kanban_columns")
            cards = ResourceStore(self.db, "kanban_cards")

            board = await boards.get(board_id)
            if not board:
                return ToolResult(success=False, data="", error=f"Board not found: {board_id}")

            col_list = await cols.list(board_id=board_id, order_by="position ASC")
            lines = [f"Board: {board['title']}"]
            if board.get("description"):
                lines.append(f"Description: {board['description']}")
            lines.append("")

            for col in col_list:
                card_list = await cards.list(column_id=col["id"], order_by="position ASC")
                lines.append(f"== {col['title']} ==")
                if card_list:
                    for card in card_list:
                        priority = card.get("priority", "medium")
                        lines.append(f"  [{priority}] {card['title']} (id: {card['id'][:8]})")
                        if card.get("description"):
                            lines.append(f"    {card['description']}")
                else:
                    lines.append("  (empty)")
                lines.append("")

            return ToolResult(success=True, data="\n".join(lines).rstrip())
        except Exception as e:
            logger.error("kanban_get_board failed: %s", e, exc_info=True)
            return ToolResult(success=False, data="", error=str(e))


class KanbanCreateBoardTool(BaseTool):
    name = "kanban_create_board"
    category = "productivity"
    description = (
        "Create a new kanban board with three default columns (To Do, Doing, Done). "
        "Returns the new board_id and the three column_ids so you can immediately "
        "create cards in any column. Use whenever the user asks you to make a board, "
        "project, task list, or workflow from scratch."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Board title (e.g. 'Credit Card Procedures')"},
            "description": {"type": "string", "description": "Optional board description"},
            "columns": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional column titles. Defaults to ['To Do', 'Doing', 'Done'] if omitted."
                ),
            },
        },
        "required": ["title"],
    }

    def __init__(self, db: Database) -> None:
        self.db = db

    async def execute(self, params: dict) -> ToolResult:
        title = (params.get("title") or "").strip()
        if not title:
            return ToolResult(success=False, data="", error="title is required")
        description = (params.get("description") or "").strip()
        column_titles = params.get("columns") or ["To Do", "Doing", "Done"]
        if not isinstance(column_titles, list) or not column_titles:
            column_titles = ["To Do", "Doing", "Done"]

        try:
            boards = ResourceStore(self.db, "kanban_boards")
            cols = ResourceStore(self.db, "kanban_columns")
            board_id = await boards.create(title=title, description=description)
            col_results = []
            for pos, col_title in enumerate(column_titles):
                col_id = await cols.create(board_id=board_id, title=col_title, position=pos)
                col_results.append((col_title, col_id))

            cols_summary = ", ".join(f'"{t}" (id: {cid[:8]})' for t, cid in col_results)
            return ToolResult(
                success=True,
                data=(
                    f"Board created: \"{title}\" (board_id: {board_id})\n"
                    f"Columns: {cols_summary}\n"
                    f"Next step: call kanban_create_card(board_id=\"{board_id}\", "
                    f"column_id=\"<one of the column ids above>\", title=\"...\") "
                    f"to add cards."
                ),
            )
        except Exception as e:
            logger.error("kanban_create_board failed: %s", e, exc_info=True)
            return ToolResult(success=False, data="", error=str(e))


class KanbanCreateCardTool(BaseTool):
    name = "kanban_create_card"
    category = "productivity"
    description = "Create a new card on a kanban board. Use when the user wants to add a task or item to a board."
    parameters_schema = {
        "type": "object",
        "properties": {
            "board_id": {"type": "string", "description": "UUID of the board (from kanban_list_boards)"},
            "column_id": {"type": "string", "description": "UUID of the target column (from kanban_get_board)"},
            "title": {"type": "string", "description": "Card title"},
            "description": {"type": "string", "description": "Card description"},
            "priority": {"type": "string", "description": "Priority: low, medium, high", "enum": ["low", "medium", "high"]},
        },
        "required": ["board_id", "column_id", "title"],
    }

    def __init__(self, db: Database) -> None:
        self.db = db

    async def execute(self, params: dict) -> ToolResult:
        board_id = params.get("board_id", "")
        column_id = params.get("column_id", "")
        title = params.get("title", "")
        description = params.get("description", "")
        priority = params.get("priority", "medium")

        if not board_id or not column_id or not title:
            return ToolResult(
                success=False, data="",
                error="board_id, column_id, and title are required",
            )

        try:
            boards = ResourceStore(self.db, "kanban_boards")
            cols = ResourceStore(self.db, "kanban_columns")
            cards = ResourceStore(self.db, "kanban_cards")

            # Validate up front so failures explain how to proceed instead of
            # leaking a raw "FOREIGN KEY constraint failed" exception.
            board = await boards.get(board_id)
            if not board:
                return ToolResult(
                    success=False, data="",
                    error=(
                        f"No board exists with id '{board_id}'. "
                        f"Create one first with kanban_create_board(title=\"...\"), "
                        f"then use the returned board_id and column_id from its response."
                    ),
                )
            column = await cols.get(column_id)
            if not column or column.get("board_id") != board_id:
                return ToolResult(
                    success=False, data="",
                    error=(
                        f"No column '{column_id}' on board '{board_id}'. "
                        f"Call kanban_get_board(board_id=\"{board_id}\") to see the "
                        f"available columns and their ids."
                    ),
                )

            existing = await cards.list(column_id=column_id, order_by="position ASC")
            position = len(existing)

            card_id = await cards.create(
                board_id=board_id,
                column_id=column_id,
                title=title,
                description=description,
                position=position,
                priority=priority,
            )
            return ToolResult(success=True, data=f"Card created: {title} (id: {card_id[:8]})")
        except Exception as e:
            logger.error("kanban_create_card failed: %s", e, exc_info=True)
            return ToolResult(success=False, data="", error=str(e))


class KanbanMoveCardTool(BaseTool):
    name = "kanban_move_card"
    category = "productivity"
    description = "Move a card to a different column on a kanban board. Use to update task status by moving between columns."
    parameters_schema = {
        "type": "object",
        "properties": {
            "board_id": {"type": "string", "description": "UUID of the board (from kanban_list_boards)"},
            "card_id": {"type": "string", "description": "UUID of the card (from kanban_get_board)"},
            "column_id": {"type": "string", "description": "UUID of the target column (from kanban_get_board)"},
        },
        "required": ["board_id", "card_id", "column_id"],
    }

    def __init__(self, db: Database) -> None:
        self.db = db

    async def execute(self, params: dict) -> ToolResult:
        card_id = params.get("card_id", "")
        column_id = params.get("column_id", "")

        try:
            cards = ResourceStore(self.db, "kanban_cards")
            card = await cards.get(card_id)
            if not card:
                return ToolResult(success=False, data="", error=f"Card not found: {card_id}")

            existing_in_col = await cards.list(column_id=column_id, order_by="position ASC")
            position = len(existing_in_col)

            updated = await cards.update(card_id, column_id=column_id, position=position)
            if not updated:
                return ToolResult(success=False, data="", error=f"Failed to move card: {card_id}")

            return ToolResult(success=True, data=f"Card moved to column {column_id[:8]} (id: {card_id[:8]})")
        except Exception as e:
            logger.error("kanban_move_card failed: %s", e, exc_info=True)
            return ToolResult(success=False, data="", error=str(e))


class KanbanUpdateCardTool(BaseTool):
    name = "kanban_update_card"
    category = "productivity"
    description = "Update a card's title or description. Use to modify existing card content."
    parameters_schema = {
        "type": "object",
        "properties": {
            "board_id": {"type": "string", "description": "UUID of the board (from kanban_list_boards)"},
            "card_id": {"type": "string", "description": "UUID of the card (from kanban_get_board)"},
            "title": {"type": "string", "description": "New title"},
            "description": {"type": "string", "description": "New description"},
            "priority": {"type": "string", "description": "New priority: low, medium, high", "enum": ["low", "medium", "high"]},
        },
        "required": ["board_id", "card_id"],
    }

    def __init__(self, db: Database) -> None:
        self.db = db

    async def execute(self, params: dict) -> ToolResult:
        card_id = params.get("card_id", "")
        updates = {}
        for field in ("title", "description", "priority"):
            if field in params:
                updates[field] = params[field]

        if not updates:
            return ToolResult(success=False, data="", error="No fields to update provided.")

        try:
            cards = ResourceStore(self.db, "kanban_cards")
            updated = await cards.update(card_id, **updates)
            if not updated:
                return ToolResult(success=False, data="", error=f"Card not found: {card_id}")
            return ToolResult(success=True, data=f"Card updated (id: {card_id[:8]})")
        except Exception as e:
            logger.error("kanban_update_card failed: %s", e, exc_info=True)
            return ToolResult(success=False, data="", error=str(e))


class KanbanDeleteCardTool(BaseTool):
    name = "kanban_delete_card"
    category = "productivity"
    description = "Delete a card from a kanban board. Use when the user explicitly asks to remove a card."
    parameters_schema = {
        "type": "object",
        "properties": {
            "board_id": {"type": "string", "description": "UUID of the board (from kanban_list_boards)"},
            "card_id": {"type": "string", "description": "UUID of the card (from kanban_get_board)"},
        },
        "required": ["board_id", "card_id"],
    }

    def __init__(self, db: Database) -> None:
        self.db = db

    async def execute(self, params: dict) -> ToolResult:
        card_id = params.get("card_id", "")
        try:
            cards = ResourceStore(self.db, "kanban_cards")
            deleted = await cards.delete(card_id)
            if not deleted:
                return ToolResult(success=False, data="", error=f"Card not found: {card_id}")
            return ToolResult(success=True, data=f"Card deleted (id: {card_id[:8]})")
        except Exception as e:
            logger.error("kanban_delete_card failed: %s", e, exc_info=True)
            return ToolResult(success=False, data="", error=str(e))
