# Kanban Board V1 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Shared kanban board between user and agent with drag-and-drop columns/cards.

**Architecture:** ResourceStore for CRUD, require_feature for gating, shadcn-kanban-board component (already installed) for frontend drag-and-drop. Separate BaseTool subclasses for agent access. Board context injected via existing context_metadata mechanism.

**Tech Stack:** Python/FastAPI, SQLite, React/TypeScript, shadcn-kanban-board, Tailwind CSS

**Spec:** `docs/superpowers/specs/2026-03-18-kanban-board-design.md`

---

## File Structure

| File | Responsibility |
|---|---|
| `migrations/039_kanban.sql` | boards, columns, cards tables |
| `odigos/api/kanban.py` | REST endpoints (CRUD + move + reorder) |
| `odigos/tools/kanban.py` | Agent tools (6 BaseTool subclasses) |
| `odigos/config.py` | KanbanConfig with enabled flag |
| `odigos/main.py` | Register router + tools |
| `odigos/core/context.py` | Add board_id context injection |
| `odigos/personality/prompt_builder.py` | Rename notebook_context to page_context |
| `dashboard/src/pages/KanbanPage.tsx` | Board list + board detail with drag-drop |
| `dashboard/src/App.tsx` | Add kanban routes |
| `dashboard/src/layouts/AppLayout.tsx` | Add kanban nav icon |
| `skills/kanban.md` | Kanban mode skill |
| `tests/test_kanban_api.py` | API integration tests |
| `tests/test_kanban_tools.py` | Agent tool tests |

---

## Chunk 1: Backend Foundation

### Task 1: Migration + Config

**Files:**
- Create: `migrations/039_kanban.sql`
- Modify: `odigos/config.py`

- [ ] **Step 1: Create migration file**

File: `migrations/039_kanban.sql`

```sql
-- Kanban board system: boards, columns, and cards.

CREATE TABLE IF NOT EXISTS kanban_boards (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kanban_columns (
    id TEXT PRIMARY KEY,
    board_id TEXT NOT NULL REFERENCES kanban_boards(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kanban_cards (
    id TEXT PRIMARY KEY,
    board_id TEXT NOT NULL REFERENCES kanban_boards(id) ON DELETE CASCADE,
    column_id TEXT NOT NULL REFERENCES kanban_columns(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    position INTEGER NOT NULL DEFAULT 0,
    priority TEXT DEFAULT 'medium',
    due_at TEXT,
    metadata TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_kanban_columns_board ON kanban_columns(board_id);
CREATE INDEX IF NOT EXISTS idx_kanban_cards_board ON kanban_cards(board_id);
CREATE INDEX IF NOT EXISTS idx_kanban_cards_column ON kanban_cards(column_id);
```

- [ ] **Step 2: Add KanbanConfig to config.py**

After `NotebooksConfig` class in `odigos/config.py`:

```python
class KanbanConfig(BaseModel):
    enabled: bool = True
```

Add to `Settings` class after `notebooks`:

```python
    kanban: KanbanConfig = KanbanConfig()
```

- [ ] **Step 3: Verify migration applies**

Run: `.venv/bin/python3 -c "import asyncio; from odigos.db import Database; db = Database(':memory:', 'migrations'); asyncio.run(db.initialize()); print('OK')"`

- [ ] **Step 4: Commit**

```bash
git add migrations/039_kanban.sql odigos/config.py
git commit -m "feat(kanban): add migration 039 and KanbanConfig"
```

---

### Task 2: Kanban API endpoints

**Files:**
- Create: `odigos/api/kanban.py`
- Modify: `odigos/main.py`
- Create: `tests/test_kanban_api.py`

- [ ] **Step 1: Write failing tests**

File: `tests/test_kanban_api.py`

```python
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from odigos.api.kanban import router
from odigos.config import Settings, KanbanConfig
from odigos.db import Database


@pytest.fixture
async def db(tmp_db_path: str) -> Database:
    database = Database(tmp_db_path, migrations_dir="migrations")
    await database.initialize()
    yield database
    await database.close()


@pytest.fixture
def app(db: Database) -> FastAPI:
    app = FastAPI()
    settings = Settings(kanban=KanbanConfig(enabled=True))
    app.state.settings = settings
    app.state.db = db
    app.include_router(router)
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


class TestBoardCRUD:
    def test_list_empty(self, client):
        resp = client.get("/api/kanban/boards")
        assert resp.status_code == 200
        assert resp.json()["boards"] == []

    def test_create_board_with_default_columns(self, client):
        resp = client.post("/api/kanban/boards", json={"title": "Sprint 1"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Sprint 1"
        assert "id" in data
        # Verify default columns created
        board = client.get(f"/api/kanban/boards/{data['id']}").json()
        columns = board["columns"]
        assert len(columns) == 4
        titles = [c["title"] for c in sorted(columns, key=lambda c: c["position"])]
        assert titles == ["Backlog", "Todo", "In Progress", "Done"]

    def test_get_board_with_columns_and_cards(self, client):
        create = client.post("/api/kanban/boards", json={"title": "Board"})
        board_id = create.json()["id"]
        board = client.get(f"/api/kanban/boards/{board_id}").json()
        assert board["title"] == "Board"
        assert "columns" in board
        assert "cards" in board

    def test_get_missing_board_404(self, client):
        assert client.get("/api/kanban/boards/nonexistent").status_code == 404

    def test_update_board(self, client):
        create = client.post("/api/kanban/boards", json={"title": "Old"})
        board_id = create.json()["id"]
        resp = client.patch(f"/api/kanban/boards/{board_id}", json={"title": "New"})
        assert resp.status_code == 200
        assert resp.json()["title"] == "New"

    def test_delete_board(self, client):
        create = client.post("/api/kanban/boards", json={"title": "Delete Me"})
        board_id = create.json()["id"]
        assert client.delete(f"/api/kanban/boards/{board_id}").status_code == 200
        assert client.get(f"/api/kanban/boards/{board_id}").status_code == 404


class TestColumnCRUD:
    def test_add_column(self, client):
        create = client.post("/api/kanban/boards", json={"title": "Board"})
        board_id = create.json()["id"]
        resp = client.post(f"/api/kanban/boards/{board_id}/columns", json={"title": "Review"})
        assert resp.status_code == 201
        assert resp.json()["title"] == "Review"
        assert resp.json()["position"] == 4  # after 4 defaults (0,1,2,3)

    def test_update_column(self, client):
        create = client.post("/api/kanban/boards", json={"title": "Board"})
        board_id = create.json()["id"]
        board = client.get(f"/api/kanban/boards/{board_id}").json()
        col_id = board["columns"][0]["id"]
        resp = client.patch(f"/api/kanban/boards/{board_id}/columns/{col_id}", json={"title": "Renamed"})
        assert resp.status_code == 200
        assert resp.json()["title"] == "Renamed"

    def test_delete_column(self, client):
        create = client.post("/api/kanban/boards", json={"title": "Board"})
        board_id = create.json()["id"]
        board = client.get(f"/api/kanban/boards/{board_id}").json()
        col_id = board["columns"][0]["id"]
        resp = client.delete(f"/api/kanban/boards/{board_id}/columns/{col_id}")
        assert resp.status_code == 200


class TestCardCRUD:
    def _get_first_column_id(self, client, board_id):
        board = client.get(f"/api/kanban/boards/{board_id}").json()
        return sorted(board["columns"], key=lambda c: c["position"])[0]["id"]

    def test_create_card(self, client):
        create = client.post("/api/kanban/boards", json={"title": "Board"})
        board_id = create.json()["id"]
        col_id = self._get_first_column_id(client, board_id)
        resp = client.post(f"/api/kanban/boards/{board_id}/cards", json={
            "column_id": col_id, "title": "Task 1",
        })
        assert resp.status_code == 201
        assert resp.json()["title"] == "Task 1"
        assert resp.json()["column_id"] == col_id

    def test_create_card_auto_position(self, client):
        create = client.post("/api/kanban/boards", json={"title": "Board"})
        board_id = create.json()["id"]
        col_id = self._get_first_column_id(client, board_id)
        c1 = client.post(f"/api/kanban/boards/{board_id}/cards", json={
            "column_id": col_id, "title": "First",
        }).json()
        c2 = client.post(f"/api/kanban/boards/{board_id}/cards", json={
            "column_id": col_id, "title": "Second",
        }).json()
        assert c1["position"] == 0
        assert c2["position"] == 1

    def test_update_card(self, client):
        create = client.post("/api/kanban/boards", json={"title": "Board"})
        board_id = create.json()["id"]
        col_id = self._get_first_column_id(client, board_id)
        card = client.post(f"/api/kanban/boards/{board_id}/cards", json={
            "column_id": col_id, "title": "Old",
        }).json()
        resp = client.patch(f"/api/kanban/boards/{board_id}/cards/{card['id']}", json={
            "title": "Updated", "priority": "high",
        })
        assert resp.status_code == 200
        assert resp.json()["title"] == "Updated"
        assert resp.json()["priority"] == "high"

    def test_delete_card(self, client):
        create = client.post("/api/kanban/boards", json={"title": "Board"})
        board_id = create.json()["id"]
        col_id = self._get_first_column_id(client, board_id)
        card = client.post(f"/api/kanban/boards/{board_id}/cards", json={
            "column_id": col_id, "title": "Delete Me",
        }).json()
        assert client.delete(f"/api/kanban/boards/{board_id}/cards/{card['id']}").status_code == 200

    def test_move_card(self, client):
        create = client.post("/api/kanban/boards", json={"title": "Board"})
        board_id = create.json()["id"]
        board = client.get(f"/api/kanban/boards/{board_id}").json()
        cols = sorted(board["columns"], key=lambda c: c["position"])
        col1_id, col2_id = cols[0]["id"], cols[1]["id"]
        card = client.post(f"/api/kanban/boards/{board_id}/cards", json={
            "column_id": col1_id, "title": "Move Me",
        }).json()
        resp = client.post(f"/api/kanban/boards/{board_id}/cards/{card['id']}/move", json={
            "column_id": col2_id, "position": 0,
        })
        assert resp.status_code == 200
        assert resp.json()["column_id"] == col2_id
        assert resp.json()["position"] == 0


class TestDisabledFeature:
    def test_disabled_returns_404(self, db):
        app = FastAPI()
        app.state.settings = Settings(kanban=KanbanConfig(enabled=False))
        app.state.db = db
        app.include_router(router)
        client = TestClient(app)
        assert client.get("/api/kanban/boards").status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python3 -m pytest tests/test_kanban_api.py -v --no-header 2>&1 | head -20`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write kanban API**

File: `odigos/api/kanban.py`

```python
"""REST API for kanban board, column, and card management."""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from odigos.api.deps import get_db, require_feature
from odigos.core.resource_store import ResourceStore

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/kanban",
    tags=["kanban"],
    dependencies=[Depends(require_feature("kanban"))],
)

_PRIORITY = Literal["low", "medium", "high", "urgent"]
_DEFAULT_COLUMNS = ["Backlog", "Todo", "In Progress", "Done"]


# -- Request models --

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


# -- Store helpers --

def _boards(db) -> ResourceStore:
    return ResourceStore(db, "kanban_boards")


def _columns(db) -> ResourceStore:
    return ResourceStore(db, "kanban_columns", parent_key="board_id")


def _cards(db) -> ResourceStore:
    return ResourceStore(db, "kanban_cards", parent_key="board_id")


async def _next_position(db, table: str, filter_col: str, filter_val: str) -> int:
    """Get next position for a new item in a group."""
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


# -- Board endpoints --

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


# -- Column endpoints --

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


# -- Card endpoints --

@router.post("/boards/{board_id}/cards", status_code=201)
async def create_card(board_id: str, body: CreateCardRequest, db=Depends(get_db)):
    await _get_board_or_404(db, board_id)
    await _get_column_or_404(db, board_id, body.column_id)
    position = await _next_position(db, "kanban_cards", "column_id", body.column_id)
    card_id = await _cards(db).create(
        board_id=board_id,
        column_id=body.column_id,
        title=body.title,
        description=body.description,
        position=position,
        priority=body.priority,
        due_at=body.due_at,
        metadata=body.metadata,
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
```

- [ ] **Step 4: Register router in main.py**

Add import after the notebooks router import:
```python
from odigos.api.kanban import router as kanban_router
```

Add registration after `app.include_router(notebooks_router)`:
```python
app.include_router(kanban_router)
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python3 -m pytest tests/test_kanban_api.py -v --no-header`
Expected: All tests PASS

- [ ] **Step 6: Run full test suite**

Run: `.venv/bin/python3 -m pytest tests/ -x -q --no-header 2>&1 | tail -5`

- [ ] **Step 7: Commit**

```bash
git add odigos/api/kanban.py odigos/main.py tests/test_kanban_api.py
git commit -m "feat(kanban): add REST API endpoints with board/column/card CRUD, move, reorder"
```

---

## Chunk 2: Agent Integration

### Task 3: Kanban agent tools

**Files:**
- Create: `odigos/tools/kanban.py`
- Create: `tests/test_kanban_tools.py`
- Modify: `odigos/main.py` (register tools)

- [ ] **Step 1: Write failing tests**

File: `tests/test_kanban_tools.py`

```python
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
    """Create a board with default columns, return (board_id, column_ids)."""
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
        assert "No boards" in result.data or "0 boards" in result.data

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
            "board_id": board_id,
            "column_id": col_ids[0],
            "title": "New Task",
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python3 -m pytest tests/test_kanban_tools.py -v --no-header 2>&1 | head -10`

- [ ] **Step 3: Write kanban tools**

File: `odigos/tools/kanban.py`

```python
"""Agent tools for kanban board management."""

from __future__ import annotations

import logging

from odigos.core.resource_store import ResourceStore
from odigos.db import Database
from odigos.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class KanbanListBoardsTool(BaseTool):
    name = "kanban_list_boards"
    description = "List all kanban boards with their column and card counts."
    parameters_schema = {"type": "object", "properties": {}}

    def __init__(self, db: Database) -> None:
        self.db = db

    async def execute(self, params: dict) -> ToolResult:
        boards = await ResourceStore(self.db, "kanban_boards").list()
        if not boards:
            return ToolResult(success=True, data="No boards found.")
        lines = [f"Found {len(boards)} board(s):"]
        for b in boards:
            card_row = await self.db.fetch_one(
                "SELECT COUNT(*) as cnt FROM kanban_cards WHERE board_id = ?", (b["id"],),
            )
            count = card_row["cnt"] if card_row else 0
            lines.append(f"- [{b['id'][:8]}] {b['title']} ({count} cards)")
        return ToolResult(success=True, data="\n".join(lines))


class KanbanGetBoardTool(BaseTool):
    name = "kanban_get_board"
    description = "Get a kanban board with all its columns and cards."
    parameters_schema = {
        "type": "object",
        "properties": {
            "board_id": {"type": "string", "description": "The board ID"},
        },
        "required": ["board_id"],
    }

    def __init__(self, db: Database) -> None:
        self.db = db

    async def execute(self, params: dict) -> ToolResult:
        board_id = params.get("board_id", "")
        board = await ResourceStore(self.db, "kanban_boards").get(board_id)
        if not board:
            return ToolResult(success=False, data="", error="Board not found")
        columns = await ResourceStore(self.db, "kanban_columns").list(
            board_id=board_id, order_by="position ASC",
        )
        cards = await ResourceStore(self.db, "kanban_cards").list(
            board_id=board_id, order_by="position ASC",
        )
        cards_by_col: dict[str, list] = {}
        for card in cards:
            cards_by_col.setdefault(card["column_id"], []).append(card)

        lines = [f"Board: {board['title']}"]
        if board.get("description"):
            lines.append(f"Description: {board['description']}")
        for col in columns:
            col_cards = cards_by_col.get(col["id"], [])
            lines.append(f"\n## {col['title']} ({len(col_cards)} cards)")
            for card in col_cards:
                priority = f" [{card['priority']}]" if card.get("priority") and card["priority"] != "medium" else ""
                lines.append(f"  - [{card['id'][:8]}] {card['title']}{priority}")
        return ToolResult(success=True, data="\n".join(lines))


class KanbanCreateCardTool(BaseTool):
    name = "kanban_create_card"
    description = "Create a new card on a kanban board in a specific column."
    parameters_schema = {
        "type": "object",
        "properties": {
            "board_id": {"type": "string", "description": "The board ID"},
            "column_id": {"type": "string", "description": "The column ID to place the card in"},
            "title": {"type": "string", "description": "Card title"},
            "description": {"type": "string", "description": "Card description (optional)"},
            "priority": {"type": "string", "enum": ["low", "medium", "high", "urgent"], "description": "Card priority (default: medium)"},
        },
        "required": ["board_id", "column_id", "title"],
    }

    def __init__(self, db: Database) -> None:
        self.db = db

    async def execute(self, params: dict) -> ToolResult:
        board_id = params.get("board_id", "")
        column_id = params.get("column_id", "")
        title = params.get("title", "")

        board = await ResourceStore(self.db, "kanban_boards").get(board_id)
        if not board:
            return ToolResult(success=False, data="", error="Board not found")
        col = await ResourceStore(self.db, "kanban_columns").get(column_id)
        if not col or col["board_id"] != board_id:
            return ToolResult(success=False, data="", error="Column not found")

        pos_row = await self.db.fetch_one(
            "SELECT COALESCE(MAX(position), -1) + 1 as pos FROM kanban_cards WHERE column_id = ?",
            (column_id,),
        )
        position = pos_row["pos"] if pos_row else 0

        card_id = await ResourceStore(self.db, "kanban_cards").create(
            board_id=board_id, column_id=column_id, title=title,
            description=params.get("description", ""),
            position=position,
            priority=params.get("priority", "medium"),
        )
        return ToolResult(success=True, data=f"Created card '{title}' (id: {card_id[:8]})")


class KanbanMoveCardTool(BaseTool):
    name = "kanban_move_card"
    description = "Move a kanban card to a different column."
    parameters_schema = {
        "type": "object",
        "properties": {
            "board_id": {"type": "string", "description": "The board ID"},
            "card_id": {"type": "string", "description": "The card ID to move"},
            "column_id": {"type": "string", "description": "Target column ID"},
            "position": {"type": "integer", "description": "Position in the target column (default: end)"},
        },
        "required": ["board_id", "card_id", "column_id"],
    }

    def __init__(self, db: Database) -> None:
        self.db = db

    async def execute(self, params: dict) -> ToolResult:
        board_id = params.get("board_id", "")
        card_id = params.get("card_id", "")
        column_id = params.get("column_id", "")

        cards = ResourceStore(self.db, "kanban_cards")
        card = await cards.get(card_id)
        if not card or card["board_id"] != board_id:
            return ToolResult(success=False, data="", error="Card not found")
        col = await ResourceStore(self.db, "kanban_columns").get(column_id)
        if not col or col["board_id"] != board_id:
            return ToolResult(success=False, data="", error="Column not found")

        position = params.get("position")
        if position is None:
            pos_row = await self.db.fetch_one(
                "SELECT COALESCE(MAX(position), -1) + 1 as pos FROM kanban_cards WHERE column_id = ?",
                (column_id,),
            )
            position = pos_row["pos"] if pos_row else 0

        await cards.update(card_id, column_id=column_id, position=position)
        return ToolResult(success=True, data=f"Moved card '{card['title']}' to column '{col['title']}'")


class KanbanUpdateCardTool(BaseTool):
    name = "kanban_update_card"
    description = "Update a kanban card's title, description, or priority."
    parameters_schema = {
        "type": "object",
        "properties": {
            "board_id": {"type": "string", "description": "The board ID"},
            "card_id": {"type": "string", "description": "The card ID to update"},
            "title": {"type": "string", "description": "New title (optional)"},
            "description": {"type": "string", "description": "New description (optional)"},
            "priority": {"type": "string", "enum": ["low", "medium", "high", "urgent"], "description": "New priority (optional)"},
        },
        "required": ["board_id", "card_id"],
    }

    def __init__(self, db: Database) -> None:
        self.db = db

    async def execute(self, params: dict) -> ToolResult:
        board_id = params.get("board_id", "")
        card_id = params.get("card_id", "")

        cards = ResourceStore(self.db, "kanban_cards")
        card = await cards.get(card_id)
        if not card or card["board_id"] != board_id:
            return ToolResult(success=False, data="", error="Card not found")

        fields = {}
        for key in ("title", "description", "priority"):
            if key in params and params[key] is not None:
                fields[key] = params[key]
        if not fields:
            return ToolResult(success=False, data="", error="No fields to update")

        await cards.update(card_id, **fields)
        return ToolResult(success=True, data=f"Updated card '{card['title']}'")


class KanbanDeleteCardTool(BaseTool):
    name = "kanban_delete_card"
    description = "Delete a card from a kanban board."
    parameters_schema = {
        "type": "object",
        "properties": {
            "board_id": {"type": "string", "description": "The board ID"},
            "card_id": {"type": "string", "description": "The card ID to delete"},
        },
        "required": ["board_id", "card_id"],
    }

    def __init__(self, db: Database) -> None:
        self.db = db

    async def execute(self, params: dict) -> ToolResult:
        board_id = params.get("board_id", "")
        card_id = params.get("card_id", "")

        cards = ResourceStore(self.db, "kanban_cards")
        card = await cards.get(card_id)
        if not card or card["board_id"] != board_id:
            return ToolResult(success=False, data="", error="Card not found")

        await cards.delete(card_id)
        return ToolResult(success=True, data=f"Deleted card '{card['title']}'")
```

- [ ] **Step 4: Register tools in main.py**

In `_register_tools()`, after the goal tools section (around line 160), add:

```python
    # Kanban tools
    from odigos.tools.kanban import (
        KanbanListBoardsTool, KanbanGetBoardTool, KanbanCreateCardTool,
        KanbanMoveCardTool, KanbanUpdateCardTool, KanbanDeleteCardTool,
    )
    tool_registry.register(KanbanListBoardsTool(db=db))
    tool_registry.register(KanbanGetBoardTool(db=db))
    tool_registry.register(KanbanCreateCardTool(db=db))
    tool_registry.register(KanbanMoveCardTool(db=db))
    tool_registry.register(KanbanUpdateCardTool(db=db))
    tool_registry.register(KanbanDeleteCardTool(db=db))
    logger.info("Kanban tools initialized")
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python3 -m pytest tests/test_kanban_tools.py tests/test_kanban_api.py -v --no-header`

- [ ] **Step 6: Run full test suite**

Run: `.venv/bin/python3 -m pytest tests/ -x -q --no-header 2>&1 | tail -5`

- [ ] **Step 7: Commit**

```bash
git add odigos/tools/kanban.py odigos/main.py tests/test_kanban_tools.py
git commit -m "feat(kanban): add agent tools — list, get, create, move, update, delete cards"
```

---

### Task 4: Board context in agent + rename notebook_context to page_context

**Files:**
- Modify: `odigos/personality/prompt_builder.py`
- Modify: `odigos/core/context.py`

- [ ] **Step 1: Rename notebook_context to page_context in prompt_builder.py**

In `odigos/personality/prompt_builder.py`, change the parameter name:

```python
    notebook_context: str = "",
```
becomes:
```python
    page_context: str = "",
```

And the usage:
```python
    if notebook_context:
        parts.append(notebook_context)
```
becomes:
```python
    if page_context:
        parts.append(page_context)
```

- [ ] **Step 2: Update context.py -- rename parameter in build_system_prompt call + add board context**

In `odigos/core/context.py`, after the notebook context block (around line 298), add board context:

```python
        # Board context (when user is on a kanban board page)
        if context_metadata and context_metadata.get("board_id") and self.db:
            try:
                board_id = context_metadata["board_id"]
                board_row = await self.db.fetch_one(
                    "SELECT title, description FROM kanban_boards WHERE id = ?",
                    (board_id,),
                )
                if board_row:
                    lines = [
                        f"## Active kanban board: \"{board_row['title']}\"",
                    ]
                    if board_row.get("description"):
                        lines.append(f"Description: {board_row['description']}")
                    col_rows = await self.db.fetch_all(
                        "SELECT id, title FROM kanban_columns WHERE board_id = ? ORDER BY position ASC",
                        (board_id,),
                    )
                    card_rows = await self.db.fetch_all(
                        "SELECT title, column_id, priority FROM kanban_cards "
                        "WHERE board_id = ? ORDER BY position ASC",
                        (board_id,),
                    )
                    cards_by_col = {}
                    for card in card_rows:
                        cards_by_col.setdefault(card["column_id"], []).append(card)
                    for col in col_rows:
                        col_cards = cards_by_col.get(col["id"], [])
                        lines.append(f"\n**{col['title']}** ({len(col_cards)} cards)")
                        for card in col_cards[:10]:
                            lines.append(f"- {card['title']}")
                    notebook_context = "\n".join(lines)
            except Exception:
                logger.debug("Could not load board context", exc_info=True)
```

Then rename the variable passed to `build_system_prompt()`:
```python
            notebook_context=notebook_context,
```
becomes:
```python
            page_context=notebook_context,
```

(The local variable `notebook_context` accumulates context from either notebooks OR boards -- it gets passed as the generic `page_context` parameter.)

- [ ] **Step 3: Run tests**

Run: `.venv/bin/python3 -m pytest tests/test_notebook_context.py tests/test_kanban_api.py -v --no-header`

- [ ] **Step 4: Run full test suite**

Run: `.venv/bin/python3 -m pytest tests/ -x -q --no-header 2>&1 | tail -5`

- [ ] **Step 5: Commit**

```bash
git add odigos/personality/prompt_builder.py odigos/core/context.py
git commit -m "feat(kanban): add board context injection, rename notebook_context to page_context"
```

---

### Task 5: Kanban skill

**Files:**
- Create: `skills/kanban.md`

- [ ] **Step 1: Create skill file**

File: `skills/kanban.md`

```markdown
---
name: kanban
description: Manage kanban boards — create cards, move tasks through columns, track progress
---

# Kanban Mode

When the user is working with a kanban board, help them manage tasks:

## Card Management
- Create cards when the user describes tasks or action items
- Move cards to appropriate columns as work progresses
- Set priority based on urgency cues in the conversation
- Suggest breaking large cards into smaller ones

## Board Awareness
- Reference the active board's columns and cards when answering questions
- Summarize board status when asked ("what's in progress?", "what's blocked?")
- Suggest next actions based on card priorities and column distribution

## Behavior
- Be proactive about updating card status when the user mentions completing work
- Ask which column to place new cards in if the board context is ambiguous
- Keep card titles concise and actionable
```

- [ ] **Step 2: Verify skill loads**

Run: `.venv/bin/python3 -c "from odigos.skills.registry import SkillRegistry; r = SkillRegistry(); r.load_all('skills'); print('kanban' in [s.name for s in r.list()])"`
Expected: `True`

- [ ] **Step 3: Commit**

```bash
git add skills/kanban.md
git commit -m "feat(kanban): add kanban mode skill"
```

---

## Chunk 3: Frontend

### Task 6: KanbanPage with drag-and-drop

**Files:**
- Create: `dashboard/src/pages/KanbanPage.tsx`
- Modify: `dashboard/src/App.tsx`
- Modify: `dashboard/src/layouts/AppLayout.tsx`

- [ ] **Step 1: Create KanbanPage.tsx**

Two views like NotebookPage:
1. **BoardList** (`/kanban`) -- list boards, create/delete
2. **BoardDetail** (`/kanban/:id`) -- columns with cards, drag-drop via shadcn-kanban-board component

The component imports from `@/components/kanban` (already installed):
- `KanbanBoard`, `KanbanBoardProvider`, `KanbanBoardColumn`, `KanbanBoardColumnHeader`

For card drag-and-drop between columns, use the `useDndEvents` hook from the kanban component. On drag end, call `POST /api/kanban/boards/{id}/cards/{cardId}/move` with the target column_id and position.

API calls use `get`, `post`, `patch`, `del` from `@/lib/api`.

Features:
- Board list with create form and delete buttons
- Board detail showing columns with cards
- Inline add card (title input at bottom of each column)
- Card delete button (hover reveal)
- Drag-and-drop cards between columns
- Add/delete columns
- Back button to board list
- Board title in header

- [ ] **Step 2: Add routes to App.tsx**

Add import:
```tsx
import KanbanPage from './pages/KanbanPage'
```

Add routes:
```tsx
<Route path="/kanban" element={<KanbanPage />} />
<Route path="/kanban/:id" element={<KanbanPage />} />
```

- [ ] **Step 3: Add nav icon to AppLayout.tsx**

Add `Columns3` to lucide-react import (kanban-style icon).

Add button before the Notebooks button in the bottom nav:
```tsx
<Tooltip>
  <TooltipTrigger>
    <button
      onClick={() => { setSidebarOpen(false); navigate('/kanban') }}
      className={`flex items-center gap-2 px-3 py-2 rounded-md text-sm transition-colors w-full ${
        location.pathname.startsWith('/kanban')
          ? 'bg-accent text-foreground'
          : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground'
      }`}
    >
      <Columns3 className="h-4 w-4 shrink-0" />{!collapsed && 'Kanban'}
    </button>
  </TooltipTrigger>
  {collapsed && <TooltipContent side="right">Kanban</TooltipContent>}
</Tooltip>
```

- [ ] **Step 4: TypeScript check and build**

Run: `cd dashboard && npx tsc --noEmit 2>&1 | head -20`
Run: `cd dashboard && npm run build 2>&1 | tail -5`

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/pages/KanbanPage.tsx dashboard/src/App.tsx dashboard/src/layouts/AppLayout.tsx
git commit -m "feat(kanban): add KanbanPage with board list, column/card CRUD, and drag-drop"
```

---

### Task 7: Final integration

- [ ] **Step 1: Run full test suite**

Run: `.venv/bin/python3 -m pytest tests/ -x -q --no-header 2>&1 | tail -5`

- [ ] **Step 2: Smoke test**

```bash
.venv/bin/python3 -c "
import asyncio
from odigos.core.resource_store import ResourceStore
from odigos.db import Database

async def test():
    db = Database(':memory:', 'migrations')
    await db.initialize()
    boards = ResourceStore(db, 'kanban_boards')
    cols = ResourceStore(db, 'kanban_columns')
    cards = ResourceStore(db, 'kanban_cards')
    bid = await boards.create(title='Sprint 1')
    cid = await cols.create(board_id=bid, title='Todo', position=0)
    kid = await cards.create(board_id=bid, column_id=cid, title='Build kanban', position=0, priority='high')
    print(f'Board: {(await boards.get(bid))[\"title\"]}')
    print(f'Column: {(await cols.get(cid))[\"title\"]}')
    print(f'Card: {(await cards.get(kid))[\"title\"]} [{(await cards.get(kid))[\"priority\"]}]')
    await db.close()
    print('OK')

asyncio.run(test())
"
```

- [ ] **Step 3: Commit any remaining changes**

```bash
git status
```
