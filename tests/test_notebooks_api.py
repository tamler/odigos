import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from odigos.api.notebooks import router
from odigos.config import Settings, NotebooksConfig
from odigos.core.resource_store import ResourceStore
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
    settings = Settings(notebooks=NotebooksConfig(enabled=True))
    app.state.settings = settings
    app.state.db = db
    app.include_router(router)
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


class TestNotebooksCRUD:
    def test_list_empty(self, client):
        resp = client.get("/api/notebooks")
        assert resp.status_code == 200
        assert resp.json()["notebooks"] == []

    def test_create_notebook(self, client):
        resp = client.post("/api/notebooks", json={"title": "My Journal", "mode": "journal"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "My Journal"
        assert data["mode"] == "journal"
        assert "id" in data

    def test_get_notebook(self, client):
        create = client.post("/api/notebooks", json={"title": "Test"})
        nb_id = create.json()["id"]
        resp = client.get(f"/api/notebooks/{nb_id}")
        assert resp.status_code == 200
        assert resp.json()["title"] == "Test"
        assert "entries" in resp.json()

    def test_get_missing_returns_404(self, client):
        resp = client.get("/api/notebooks/nonexistent")
        assert resp.status_code == 404

    def test_update_notebook(self, client):
        create = client.post("/api/notebooks", json={"title": "Old"})
        nb_id = create.json()["id"]
        resp = client.patch(f"/api/notebooks/{nb_id}", json={"title": "New"})
        assert resp.status_code == 200
        assert resp.json()["title"] == "New"

    def test_delete_notebook(self, client):
        create = client.post("/api/notebooks", json={"title": "Delete Me"})
        nb_id = create.json()["id"]
        resp = client.delete(f"/api/notebooks/{nb_id}")
        assert resp.status_code == 200
        assert client.get(f"/api/notebooks/{nb_id}").status_code == 404


class TestNotebookEntries:
    def test_add_entry(self, client):
        create = client.post("/api/notebooks", json={"title": "NB"})
        nb_id = create.json()["id"]
        resp = client.post(f"/api/notebooks/{nb_id}/entries", json={
            "content": "What went well today?",
            "entry_type": "user",
        })
        assert resp.status_code == 201
        assert resp.json()["content"] == "What went well today?"

    def test_update_entry(self, client):
        create = client.post("/api/notebooks", json={"title": "NB"})
        nb_id = create.json()["id"]
        entry = client.post(f"/api/notebooks/{nb_id}/entries", json={
            "content": "Original",
        })
        entry_id = entry.json()["id"]
        resp = client.patch(f"/api/notebooks/{nb_id}/entries/{entry_id}", json={
            "content": "Updated",
        })
        assert resp.status_code == 200
        assert resp.json()["content"] == "Updated"

    def test_delete_entry(self, client):
        create = client.post("/api/notebooks", json={"title": "NB"})
        nb_id = create.json()["id"]
        entry = client.post(f"/api/notebooks/{nb_id}/entries", json={
            "content": "Delete me",
        })
        entry_id = entry.json()["id"]
        resp = client.delete(f"/api/notebooks/{nb_id}/entries/{entry_id}")
        assert resp.status_code == 200

    def test_accept_suggestion(self, client):
        create = client.post("/api/notebooks", json={"title": "NB"})
        nb_id = create.json()["id"]
        entry = client.post(f"/api/notebooks/{nb_id}/entries", json={
            "content": "Agent suggestion",
            "entry_type": "agent_suggestion",
            "status": "pending",
        })
        entry_id = entry.json()["id"]
        resp = client.post(f"/api/notebooks/{nb_id}/entries/{entry_id}/accept")
        assert resp.status_code == 200
        assert resp.json()["status"] == "accepted"
        assert resp.json()["entry_type"] == "agent"

    def test_reject_suggestion(self, client):
        create = client.post("/api/notebooks", json={"title": "NB"})
        nb_id = create.json()["id"]
        entry = client.post(f"/api/notebooks/{nb_id}/entries", json={
            "content": "Agent suggestion",
            "entry_type": "agent_suggestion",
            "status": "pending",
        })
        entry_id = entry.json()["id"]
        resp = client.post(f"/api/notebooks/{nb_id}/entries/{entry_id}/reject")
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"


class TestDisabledFeature:
    def test_disabled_returns_404(self, db):
        app = FastAPI()
        app.state.settings = Settings(notebooks=NotebooksConfig(enabled=False))
        app.state.db = db
        app.include_router(router)
        client = TestClient(app)
        resp = client.get("/api/notebooks")
        assert resp.status_code == 404
