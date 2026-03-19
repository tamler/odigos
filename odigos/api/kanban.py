"""REST API for kanban board, column, and card management."""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from odigos.api.deps import get_db, require_auth, require_feature
from odigos.core.resource_store import ResourceStore

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/kanban",
    tags=["kanban"],
    dependencies=[Depends(require_auth), Depends(require_feature("kanban"))],
)

_PRIORITY = Literal["low", "medium", "high", "urgent"]
_DEFAULT_COLUMNS = ["Backlog", "Todo", "In Progress", "Done"]


class CreateBoardRequest(BaseModel):
    title: str
    description: str = ""

class UpdateBoardRequest(BaseModel):
    title: str | None = None
    description: str | None = None

class CreateColumnRequest(BaseModel):
    title: str
    position: int | None = None

class UpdateColumnRequest(BaseModel):
    title: str | None = None
    position: int | None = None

class CreateCardRequest(BaseModel):
    column_id: str
    title: str
    description: str = ""
    priority: _PRIORITY = "medium"
    due_at: str | None = None
    metadata: str | None = None

class UpdateCardRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    column_id: str | None = None
    position: int | None = None
    priority: _PRIORITY | None = None
    due_at: str | None = None
    metadata: str | None = None

class MoveCardRequest(BaseModel):
    column_id: str
    position: int = 0

class ReorderItem(BaseModel):
    id: str
    position: int
    column_id: str | None = None

class ReorderRequest(BaseModel):
    columns: list[ReorderItem] | None = None
    cards: list[ReorderItem] | None = None


def _boards(db) -> ResourceStore:
    return ResourceStore(db, "kanban_boards")

def _columns(db) -> ResourceStore:
    return ResourceStore(db, "kanban_columns", parent_key="board_id")

def _cards(db) -> ResourceStore:
    return ResourceStore(db, "kanban_cards", parent_key="board_id")

async def _next_position(db, table: str, filter_col: str, filter_val: str) -> int:
    row = await db.fetch_one(
        f"SELECT COALESCE(MAX(position), -1) + 1 as next_pos FROM {table} WHERE {filter_col} = ?",
        (filter_val,),
    )
    return row["next_pos"] if row else 0

async def _get_board_or_404(db, board_id: str) -> dict:
    board = await _boards(db).get(board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")
    return board

async def _get_column_or_404(db, board_id: str, col_id: str) -> dict:
    col = await _columns(db).get(col_id)
    if not col or col["board_id"] != board_id:
        raise HTTPException(status_code=404, detail="Column not found")
    return col

async def _get_card_or_404(db, board_id: str, card_id: str) -> dict:
    card = await _cards(db).get(card_id)
    if not card or card["board_id"] != board_id:
        raise HTTPException(status_code=404, detail="Card not found")
    return card


@router.get("/boards")
async def list_boards(db=Depends(get_db)):
    boards = await _boards(db).list()
    return {"boards": boards}

@router.post("/boards", status_code=201)
async def create_board(body: CreateBoardRequest, db=Depends(get_db)):
    board_id = await _boards(db).create(title=body.title, description=body.description)
    cols = _columns(db)
    for i, title in enumerate(_DEFAULT_COLUMNS):
        await cols.create(board_id=board_id, title=title, position=i)
    return await _boards(db).get(board_id)

@router.get("/boards/{board_id}")
async def get_board(board_id: str, db=Depends(get_db)):
    board = await _get_board_or_404(db, board_id)
    columns = await _columns(db).list(board_id=board_id, order_by="position ASC")
    cards = await _cards(db).list(board_id=board_id, order_by="position ASC")
    return {**board, "columns": columns, "cards": cards}

@router.patch("/boards/{board_id}")
async def update_board(board_id: str, body: UpdateBoardRequest, db=Depends(get_db)):
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    updated = await _boards(db).update(board_id, **fields)
    if not updated:
        raise HTTPException(status_code=404, detail="Board not found")
    return await _boards(db).get(board_id)

@router.delete("/boards/{board_id}")
async def delete_board(board_id: str, db=Depends(get_db)):
    deleted = await _boards(db).delete(board_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Board not found")
    return {"deleted": True}

@router.post("/boards/{board_id}/columns", status_code=201)
async def create_column(board_id: str, body: CreateColumnRequest, db=Depends(get_db)):
    await _get_board_or_404(db, board_id)
    position = body.position
    if position is None:
        position = await _next_position(db, "kanban_columns", "board_id", board_id)
    col_id = await _columns(db).create(board_id=board_id, title=body.title, position=position)
    return await _columns(db).get(col_id)

@router.patch("/boards/{board_id}/columns/{col_id}")
async def update_column(board_id: str, col_id: str, body: UpdateColumnRequest, db=Depends(get_db)):
    await _get_column_or_404(db, board_id, col_id)
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    await _columns(db).update(col_id, **fields)
    return await _columns(db).get(col_id)

@router.delete("/boards/{board_id}/columns/{col_id}")
async def delete_column(board_id: str, col_id: str, db=Depends(get_db)):
    await _get_column_or_404(db, board_id, col_id)
    await _columns(db).delete(col_id)
    return {"deleted": True}

@router.post("/boards/{board_id}/cards", status_code=201)
async def create_card(board_id: str, body: CreateCardRequest, db=Depends(get_db)):
    await _get_board_or_404(db, board_id)
    await _get_column_or_404(db, board_id, body.column_id)
    position = await _next_position(db, "kanban_cards", "column_id", body.column_id)
    card_id = await _cards(db).create(
        board_id=board_id, column_id=body.column_id, title=body.title,
        description=body.description, position=position, priority=body.priority,
        due_at=body.due_at, metadata=body.metadata,
    )
    return await _cards(db).get(card_id)

@router.patch("/boards/{board_id}/cards/{card_id}")
async def update_card(board_id: str, card_id: str, body: UpdateCardRequest, db=Depends(get_db)):
    await _get_card_or_404(db, board_id, card_id)
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    await _cards(db).update(card_id, **fields)
    return await _cards(db).get(card_id)

@router.delete("/boards/{board_id}/cards/{card_id}")
async def delete_card(board_id: str, card_id: str, db=Depends(get_db)):
    await _get_card_or_404(db, board_id, card_id)
    await _cards(db).delete(card_id)
    return {"deleted": True}

@router.post("/boards/{board_id}/cards/{card_id}/move")
async def move_card(board_id: str, card_id: str, body: MoveCardRequest, db=Depends(get_db)):
    await _get_card_or_404(db, board_id, card_id)
    await _get_column_or_404(db, board_id, body.column_id)
    await _cards(db).update(card_id, column_id=body.column_id, position=body.position)
    return await _cards(db).get(card_id)

@router.patch("/boards/{board_id}/reorder")
async def reorder(board_id: str, body: ReorderRequest, db=Depends(get_db)):
    await _get_board_or_404(db, board_id)
    if not body.columns and not body.cards:
        raise HTTPException(status_code=400, detail="Nothing to reorder")
    if body.columns:
        for item in body.columns:
            await _columns(db).update(item.id, position=item.position)
    if body.cards:
        for item in body.cards:
            fields: dict = {"position": item.position}
            if item.column_id:
                fields["column_id"] = item.column_id
            await _cards(db).update(item.id, **fields)
    return {"reordered": True}
