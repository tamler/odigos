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
    description = "List all kanban boards with card counts."
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
    description = "Get a kanban board with its columns and cards formatted as text."
    parameters_schema = {
        "type": "object",
        "properties": {
            "board_id": {"type": "string", "description": "The board id"},
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


class KanbanCreateCardTool(BaseTool):
    name = "kanban_create_card"
    description = "Create a new card in a kanban column."
    parameters_schema = {
        "type": "object",
        "properties": {
            "board_id": {"type": "string", "description": "The board id"},
            "column_id": {"type": "string", "description": "The column id"},
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

        try:
            cards = ResourceStore(self.db, "kanban_cards")
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
    description = "Move a kanban card to a different column."
    parameters_schema = {
        "type": "object",
        "properties": {
            "board_id": {"type": "string", "description": "The board id"},
            "card_id": {"type": "string", "description": "The card id"},
            "column_id": {"type": "string", "description": "The destination column id"},
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
    description = "Update a kanban card's title, description, or priority."
    parameters_schema = {
        "type": "object",
        "properties": {
            "board_id": {"type": "string", "description": "The board id"},
            "card_id": {"type": "string", "description": "The card id"},
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
    description = "Delete a kanban card."
    parameters_schema = {
        "type": "object",
        "properties": {
            "board_id": {"type": "string", "description": "The board id"},
            "card_id": {"type": "string", "description": "The card id"},
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
