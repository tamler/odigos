"""Tests for public sharing endpoints (notebooks & kanban boards)."""
import pytest
from types import SimpleNamespace

from fastapi import FastAPI
from starlette.testclient import TestClient

from odigos.container import Container
from odigos.db import Database


@pytest.fixture
async def db(tmp_path):
    d = Database(str(tmp_path / "test.db"))
    await d.initialize()
    return d


def _make_app(db):
    from odigos.api.sharing import router, public_router
    app = FastAPI()
    app.include_router(router)
    app.include_router(public_router)
    app.state.container = Container(
        settings=SimpleNamespace(
            api_key="test-key",
            session_secret="",
            agent=SimpleNamespace(name="TestBot"),
        ),
        db=db,
    )
    return app


AUTH = {"Authorization": "Bearer test-key"}


class TestNotebookSharing:
    @pytest.mark.asyncio
    async def test_share_notebook(self, db):
        await db.execute(
            "INSERT INTO notebooks (id, title, created_at, updated_at) VALUES (?, ?, datetime('now'), datetime('now'))",
            ("nb-1", "My Notes"),
        )
        app = _make_app(db)
        client = TestClient(app)

        resp = client.post("/api/notebooks/nb-1/share", headers=AUTH)
        assert resp.status_code == 200
        data = resp.json()
        assert "share_token" in data
        assert data["url"].startswith("/shared/notebook/")

        # Second call returns same token
        resp2 = client.post("/api/notebooks/nb-1/share", headers=AUTH)
        assert resp2.json()["share_token"] == data["share_token"]

    @pytest.mark.asyncio
    async def test_public_notebook_view(self, db):
        await db.execute(
            "INSERT INTO notebooks (id, title, share_token, created_at, updated_at) VALUES (?, ?, ?, datetime('now'), datetime('now'))",
            ("nb-2", "Shared Notes", "tok123"),
        )
        await db.execute(
            "INSERT INTO notebook_entries (id, notebook_id, content, created_at, updated_at) VALUES (?, ?, ?, datetime('now'), datetime('now'))",
            ("e1", "nb-2", "Hello world"),
        )
        app = _make_app(db)
        client = TestClient(app)

        resp = client.get("/shared/notebook/tok123")
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Shared Notes"
        assert len(data["entries"]) == 1

    @pytest.mark.asyncio
    async def test_invalid_token_404(self, db):
        app = _make_app(db)
        client = TestClient(app)
        resp = client.get("/shared/notebook/nonexistent")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_revoke_share(self, db):
        await db.execute(
            "INSERT INTO notebooks (id, title, share_token, created_at, updated_at) VALUES (?, ?, ?, datetime('now'), datetime('now'))",
            ("nb-3", "Revokable", "tok456"),
        )
        app = _make_app(db)
        client = TestClient(app)

        resp = client.delete("/api/notebooks/nb-3/share", headers=AUTH)
        assert resp.status_code == 200

        # Token no longer works
        resp = client.get("/shared/notebook/tok456")
        assert resp.status_code == 404


class TestKanbanSharing:
    @pytest.mark.asyncio
    async def test_share_board(self, db):
        await db.execute(
            "INSERT INTO kanban_boards (id, title, created_at, updated_at) VALUES (?, ?, datetime('now'), datetime('now'))",
            ("board-1", "Project Board"),
        )
        app = _make_app(db)
        client = TestClient(app)

        resp = client.post("/api/kanban/boards/board-1/share", headers=AUTH)
        assert resp.status_code == 200
        data = resp.json()
        assert "share_token" in data

    @pytest.mark.asyncio
    async def test_public_board_view(self, db):
        await db.execute(
            "INSERT INTO kanban_boards (id, title, share_token, created_at, updated_at) VALUES (?, ?, ?, datetime('now'), datetime('now'))",
            ("board-2", "Shared Board", "btok789"),
        )
        await db.execute(
            "INSERT INTO kanban_columns (id, board_id, title, position, created_at, updated_at) VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))",
            ("col-1", "board-2", "To Do", 0),
        )
        await db.execute(
            "INSERT INTO kanban_cards (id, board_id, column_id, title, position, created_at, updated_at) VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            ("card-1", "board-2", "col-1", "Task 1", 0),
        )
        app = _make_app(db)
        client = TestClient(app)

        resp = client.get("/shared/board/btok789")
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Shared Board"
        assert len(data["columns"]) == 1
        assert len(data["cards"]) == 1

    @pytest.mark.asyncio
    async def test_share_requires_auth(self, db):
        app = _make_app(db)
        client = TestClient(app)
        resp = client.post("/api/kanban/boards/board-1/share")
        assert resp.status_code == 401
