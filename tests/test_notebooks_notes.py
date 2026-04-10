"""Tests for notebook review sidecar extensions to notebook_entries."""
from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from odigos.api.notebooks import router
from odigos.config import Settings, NotebooksConfig
from odigos.container import Container
from odigos.db import Database


def _make_app(db: Database) -> FastAPI:
    app = FastAPI()
    settings = Settings(notebooks=NotebooksConfig(enabled=True), api_key="test-key")
    container = Container(settings=settings, db=db)
    app.state.container = container
    app.include_router(router)
    return app


@pytest_asyncio.fixture
async def db(tmp_db_path: str):
    d = Database(tmp_db_path, migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


@pytest_asyncio.fixture
async def client(db: Database) -> AsyncClient:
    app = _make_app(db)
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": "Bearer test-key"},
    ) as c:
        yield c


class TestSchemaExtensions:
    async def test_notebook_entries_has_quote_column(self, db):
        # Insert a notebook and entry with the new quote field
        nb_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO notebooks (id, title, created_at, updated_at) VALUES (?, ?, datetime('now'), datetime('now'))",
            (nb_id, "Test"),
        )
        entry_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO notebook_entries (id, notebook_id, content, entry_type, quote, trigger_type, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            (entry_id, nb_id, "Observation body", "agent", "original text", "heartbeat"),
        )
        row = await db.fetch_one(
            "SELECT quote, trigger_type FROM notebook_entries WHERE id = ?",
            (entry_id,),
        )
        assert row["quote"] == "original text"
        assert row["trigger_type"] == "heartbeat"

    async def test_notebook_entries_has_viewed_at_column(self, db):
        nb_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO notebooks (id, title, created_at, updated_at) VALUES (?, ?, datetime('now'), datetime('now'))",
            (nb_id, "Test"),
        )
        entry_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO notebook_entries (id, notebook_id, content, entry_type, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))",
            (entry_id, nb_id, "body", "agent"),
        )
        # viewed_at should default to NULL
        row = await db.fetch_one(
            "SELECT viewed_at FROM notebook_entries WHERE id = ?",
            (entry_id,),
        )
        assert row["viewed_at"] is None

    async def test_notebook_entries_has_parent_id_column(self, db):
        nb_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO notebooks (id, title, created_at, updated_at) VALUES (?, ?, datetime('now'), datetime('now'))",
            (nb_id, "Test"),
        )
        parent_id = str(uuid.uuid4())
        child_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO notebook_entries (id, notebook_id, content, entry_type, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))",
            (parent_id, nb_id, "agent observation", "agent"),
        )
        await db.execute(
            "INSERT INTO notebook_entries (id, notebook_id, content, entry_type, parent_id, trigger_type, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            (child_id, nb_id, "user reply", "user", parent_id, "reply"),
        )
        row = await db.fetch_one(
            "SELECT parent_id FROM notebook_entries WHERE id = ?",
            (child_id,),
        )
        assert row["parent_id"] == parent_id

    async def test_notebooks_has_last_reviewed_at_column(self, db):
        nb_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO notebooks (id, title, last_reviewed_at, created_at, updated_at) VALUES (?, ?, ?, datetime('now'), datetime('now'))",
            (nb_id, "Test", "2026-04-10T12:00:00Z"),
        )
        row = await db.fetch_one(
            "SELECT last_reviewed_at FROM notebooks WHERE id = ?",
            (nb_id,),
        )
        assert row["last_reviewed_at"] == "2026-04-10T12:00:00Z"


class TestEntryFilters:
    async def test_create_entry_with_new_fields(self, client: AsyncClient, db):
        # Create a notebook first
        resp = await client.post("/api/notebooks", json={"title": "Test"})
        assert resp.status_code == 201
        nb_id = resp.json()["id"]

        # Create an agent entry with quote + trigger_type
        resp = await client.post(
            f"/api/notebooks/{nb_id}/entries",
            json={
                "content": "You mentioned deployment frustration before",
                "entry_type": "agent",
                "quote": "I'm spinning my wheels",
                "trigger_type": "heartbeat",
            },
        )
        assert resp.status_code == 201
        entry = resp.json()
        assert entry["quote"] == "I'm spinning my wheels"
        assert entry["trigger_type"] == "heartbeat"
        assert entry["entry_type"] == "agent"

    async def test_list_entries_filter_by_entry_type(self, client: AsyncClient):
        resp = await client.post("/api/notebooks", json={"title": "Test"})
        nb_id = resp.json()["id"]

        await client.post(
            f"/api/notebooks/{nb_id}/entries",
            json={"content": "User writing", "entry_type": "user"},
        )
        await client.post(
            f"/api/notebooks/{nb_id}/entries",
            json={"content": "Agent note", "entry_type": "agent", "trigger_type": "heartbeat"},
        )

        # Filter to only agent entries
        resp = await client.get(f"/api/notebooks/{nb_id}/entries?entry_type=agent")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["entries"]) == 1
        assert data["entries"][0]["content"] == "Agent note"
        assert data["unread_count"] == 1

    async def test_list_entries_include_dead(self, client: AsyncClient, db):
        resp = await client.post("/api/notebooks", json={"title": "Test"})
        nb_id = resp.json()["id"]

        resp = await client.post(
            f"/api/notebooks/{nb_id}/entries",
            json={"content": "Dead note", "entry_type": "agent", "trigger_type": "heartbeat"},
        )
        entry_id = resp.json()["id"]
        await db.execute(
            "UPDATE notebook_entries SET status = 'dead' WHERE id = ?",
            (entry_id,),
        )

        # Default: dead entries excluded
        resp = await client.get(f"/api/notebooks/{nb_id}/entries?entry_type=agent")
        assert len(resp.json()["entries"]) == 0

        # include_dead=true: dead entries included
        resp = await client.get(
            f"/api/notebooks/{nb_id}/entries?entry_type=agent&include_dead=true"
        )
        assert len(resp.json()["entries"]) == 1


class TestViewTracking:
    async def test_mark_entry_viewed(self, client: AsyncClient):
        resp = await client.post("/api/notebooks", json={"title": "Test"})
        nb_id = resp.json()["id"]

        resp = await client.post(
            f"/api/notebooks/{nb_id}/entries",
            json={"content": "Agent note", "entry_type": "agent", "trigger_type": "heartbeat"},
        )
        entry_id = resp.json()["id"]

        resp = await client.post(
            f"/api/notebooks/{nb_id}/entries/{entry_id}/view"
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

        # Verify viewed_at is now set
        resp = await client.get(f"/api/notebooks/{nb_id}/entries?entry_type=agent")
        entry = resp.json()["entries"][0]
        assert entry["viewed_at"] is not None
        assert resp.json()["unread_count"] == 0

    async def test_mark_all_viewed(self, client: AsyncClient):
        resp = await client.post("/api/notebooks", json={"title": "Test"})
        nb_id = resp.json()["id"]

        for i in range(3):
            await client.post(
                f"/api/notebooks/{nb_id}/entries",
                json={
                    "content": f"Note {i}",
                    "entry_type": "agent",
                    "trigger_type": "heartbeat",
                },
            )

        resp = await client.post(
            f"/api/notebooks/{nb_id}/mark-all-viewed?entry_type=agent"
        )
        assert resp.status_code == 200
        assert resp.json()["marked"] == 3

        resp = await client.get(f"/api/notebooks/{nb_id}/entries?entry_type=agent")
        assert resp.json()["unread_count"] == 0


class TestSplitBackup:
    async def test_backup_writes_user_file_only_when_no_agent_notes(
        self, client: AsyncClient, tmp_path, monkeypatch
    ):
        # Monkeypatch the backup dir to a temp location
        from odigos.api import notebooks as notebooks_module
        monkeypatch.setattr(notebooks_module, "BACKUP_DIR", tmp_path)

        resp = await client.post("/api/notebooks", json={"title": "Test"})
        nb_id = resp.json()["id"]

        await client.post(
            f"/api/notebooks/{nb_id}/entries",
            json={"content": "User writing here", "entry_type": "user"},
        )

        # Main file should exist, sidecar should not
        main_file = tmp_path / f"{nb_id}.md"
        sidecar = tmp_path / f"{nb_id}.note.md"
        assert main_file.exists()
        assert not sidecar.exists()
        assert "User writing here" in main_file.read_text()

    async def test_backup_writes_both_files_when_agent_notes_exist(
        self, client: AsyncClient, tmp_path, monkeypatch
    ):
        from odigos.api import notebooks as notebooks_module
        monkeypatch.setattr(notebooks_module, "BACKUP_DIR", tmp_path)

        resp = await client.post("/api/notebooks", json={"title": "Test"})
        nb_id = resp.json()["id"]

        await client.post(
            f"/api/notebooks/{nb_id}/entries",
            json={"content": "My journal entry", "entry_type": "user"},
        )
        await client.post(
            f"/api/notebooks/{nb_id}/entries",
            json={
                "content": "Pattern observed",
                "entry_type": "agent",
                "quote": "my journal",
                "trigger_type": "heartbeat",
            },
        )

        main_file = tmp_path / f"{nb_id}.md"
        sidecar = tmp_path / f"{nb_id}.note.md"
        assert main_file.exists()
        assert sidecar.exists()

        # User entries only in main file
        main_content = main_file.read_text()
        assert "My journal entry" in main_content
        assert "Pattern observed" not in main_content

        # Agent entries only in sidecar
        sidecar_content = sidecar.read_text()
        assert "Pattern observed" in sidecar_content
        assert "My journal entry" not in sidecar_content
        assert "heartbeat" in sidecar_content
        assert '"my journal"' in sidecar_content or "> my journal" in sidecar_content

    async def test_backup_sidecar_contains_toc(
        self, client: AsyncClient, tmp_path, monkeypatch
    ):
        from odigos.api import notebooks as notebooks_module
        monkeypatch.setattr(notebooks_module, "BACKUP_DIR", tmp_path)

        resp = await client.post("/api/notebooks", json={"title": "Test"})
        nb_id = resp.json()["id"]

        await client.post(
            f"/api/notebooks/{nb_id}/entries",
            json={"content": "First observation", "entry_type": "agent", "trigger_type": "heartbeat"},
        )
        await client.post(
            f"/api/notebooks/{nb_id}/entries",
            json={"content": "Second observation", "entry_type": "agent", "trigger_type": "heartbeat"},
        )

        sidecar = tmp_path / f"{nb_id}.note.md"
        content = sidecar.read_text()
        assert "## Contents" in content
        assert "entries: 2" in content
        assert "active: 2" in content
