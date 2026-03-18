import pytest

from odigos.core.resource_store import ResourceStore
from odigos.db import Database
from odigos.tools.kanban import (
    KanbanListBoardsTool,
    KanbanGetBoardTool,
    KanbanCreateCardTool,
    KanbanMoveCardTool,
    KanbanUpdateCardTool,
    KanbanDeleteCardTool,
)


@pytest.fixture
async def db(tmp_db_path: str) -> Database:
    database = Database(tmp_db_path, migrations_dir="migrations")
    await database.initialize()
    yield database
    await database.close()


@pytest.fixture
async def board_with_columns(db):
    boards = ResourceStore(db, "kanban_boards")
    cols = ResourceStore(db, "kanban_columns")
    board_id = await boards.create(title="Test Board", description="")
    col_ids = []
    for i, title in enumerate(["Backlog", "Todo", "In Progress", "Done"]):
        cid = await cols.create(board_id=board_id, title=title, position=i)
        col_ids.append(cid)
    return board_id, col_ids


class TestKanbanListBoards:
    async def test_list_empty(self, db):
        tool = KanbanListBoardsTool(db=db)
        result = await tool.execute({})
        assert result.success

    async def test_list_with_boards(self, db, board_with_columns):
        tool = KanbanListBoardsTool(db=db)
        result = await tool.execute({})
        assert result.success
        assert "Test Board" in result.data


class TestKanbanGetBoard:
    async def test_get_board(self, db, board_with_columns):
        board_id, _ = board_with_columns
        tool = KanbanGetBoardTool(db=db)
        result = await tool.execute({"board_id": board_id})
        assert result.success
        assert "Test Board" in result.data
        assert "Backlog" in result.data

    async def test_get_missing_board(self, db):
        tool = KanbanGetBoardTool(db=db)
        result = await tool.execute({"board_id": "nonexistent"})
        assert not result.success


class TestKanbanCreateCard:
    async def test_create_card(self, db, board_with_columns):
        board_id, col_ids = board_with_columns
        tool = KanbanCreateCardTool(db=db)
        result = await tool.execute({
            "board_id": board_id, "column_id": col_ids[0], "title": "New Task",
        })
        assert result.success
        assert "New Task" in result.data


class TestKanbanMoveCard:
    async def test_move_card(self, db, board_with_columns):
        board_id, col_ids = board_with_columns
        cards = ResourceStore(db, "kanban_cards")
        card_id = await cards.create(
            board_id=board_id, column_id=col_ids[0], title="Move Me", position=0, priority="medium",
        )
        tool = KanbanMoveCardTool(db=db)
        result = await tool.execute({
            "board_id": board_id, "card_id": card_id, "column_id": col_ids[1],
        })
        assert result.success
        card = await cards.get(card_id)
        assert card["column_id"] == col_ids[1]


class TestKanbanUpdateCard:
    async def test_update_card(self, db, board_with_columns):
        board_id, col_ids = board_with_columns
        cards = ResourceStore(db, "kanban_cards")
        card_id = await cards.create(
            board_id=board_id, column_id=col_ids[0], title="Old", position=0, priority="medium",
        )
        tool = KanbanUpdateCardTool(db=db)
        result = await tool.execute({
            "board_id": board_id, "card_id": card_id, "title": "New", "priority": "high",
        })
        assert result.success
        card = await cards.get(card_id)
        assert card["title"] == "New"
        assert card["priority"] == "high"


class TestKanbanDeleteCard:
    async def test_delete_card(self, db, board_with_columns):
        board_id, col_ids = board_with_columns
        cards = ResourceStore(db, "kanban_cards")
        card_id = await cards.create(
            board_id=board_id, column_id=col_ids[0], title="Delete Me", position=0, priority="medium",
        )
        tool = KanbanDeleteCardTool(db=db)
        result = await tool.execute({"board_id": board_id, "card_id": card_id})
        assert result.success
        assert await cards.get(card_id) is None
