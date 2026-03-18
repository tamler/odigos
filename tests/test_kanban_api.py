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
        assert resp.json()["position"] == 4

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
