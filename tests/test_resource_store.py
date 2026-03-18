import uuid
from datetime import datetime, timezone

import pytest

from odigos.core.resource_store import ResourceStore
from odigos.db import Database


@pytest.fixture
async def db(tmp_db_path: str) -> Database:
    database = Database(tmp_db_path, migrations_dir="migrations")
    await database.initialize()
    yield database
    await database.close()


@pytest.fixture
def store(db: Database) -> ResourceStore:
    return ResourceStore(db, "notebooks")


@pytest.fixture
def entry_store(db: Database) -> ResourceStore:
    return ResourceStore(db, "notebook_entries", parent_key="notebook_id")


class TestResourceStoreCreate:
    async def test_create_returns_id(self, store):
        row_id = await store.create(
            title="Test Notebook",
            mode="journal",
            collaboration="read",
            share_with_agent=0,
        )
        assert isinstance(row_id, str)
        assert len(row_id) == 36  # UUID format with dashes

    async def test_create_sets_timestamps(self, store):
        row_id = await store.create(title="Test", mode="general")
        row = await store.get(row_id)
        assert row is not None
        assert row["created_at"] is not None
        assert row["updated_at"] is not None


class TestResourceStoreGet:
    async def test_get_existing(self, store):
        row_id = await store.create(title="My Notebook", mode="journal")
        row = await store.get(row_id)
        assert row is not None
        assert row["title"] == "My Notebook"
        assert row["mode"] == "journal"

    async def test_get_missing_returns_none(self, store):
        row = await store.get("nonexistent-id")
        assert row is None


class TestResourceStoreList:
    async def test_list_empty(self, store):
        rows = await store.list()
        assert rows == []

    async def test_list_with_filter(self, store):
        await store.create(title="Journal", mode="journal")
        await store.create(title="Research", mode="research")
        rows = await store.list(mode="journal")
        assert len(rows) == 1
        assert rows[0]["title"] == "Journal"

    async def test_list_with_limit(self, store):
        for i in range(5):
            await store.create(title=f"Notebook {i}", mode="general")
        rows = await store.list(limit=3)
        assert len(rows) == 3

    async def test_list_ordered_by_created_at_desc(self, store):
        id1 = await store.create(title="First", mode="general")
        id2 = await store.create(title="Second", mode="general")
        rows = await store.list()
        assert rows[0]["title"] == "Second"
        assert rows[1]["title"] == "First"


class TestResourceStoreUpdate:
    async def test_update_fields(self, store):
        row_id = await store.create(title="Old Title", mode="general")
        result = await store.update(row_id, title="New Title")
        assert result is True
        row = await store.get(row_id)
        assert row["title"] == "New Title"

    async def test_update_sets_updated_at(self, store):
        row_id = await store.create(title="Test", mode="general")
        row_before = await store.get(row_id)
        await store.update(row_id, title="Updated")
        row_after = await store.get(row_id)
        assert row_after["updated_at"] >= row_before["updated_at"]

    async def test_update_nonexistent_returns_false(self, store):
        result = await store.update("nonexistent", title="Nope")
        assert result is False


class TestResourceStoreDelete:
    async def test_delete_existing(self, store):
        row_id = await store.create(title="Delete Me", mode="general")
        result = await store.delete(row_id)
        assert result is True
        assert await store.get(row_id) is None

    async def test_delete_nonexistent_returns_false(self, store):
        result = await store.delete("nonexistent")
        assert result is False


class TestResourceStoreParentKey:
    async def test_list_by_parent(self, store, entry_store):
        nb_id = await store.create(title="NB", mode="general")
        await entry_store.create(
            notebook_id=nb_id, content="Entry 1", entry_type="user", status="active",
        )
        await entry_store.create(
            notebook_id=nb_id, content="Entry 2", entry_type="user", status="active",
        )
        entries = await entry_store.list(notebook_id=nb_id)
        assert len(entries) == 2

    async def test_cascade_delete(self, db, store, entry_store):
        nb_id = await store.create(title="NB", mode="general")
        await entry_store.create(
            notebook_id=nb_id, content="Entry", entry_type="user", status="active",
        )
        await store.delete(nb_id)
        entries = await entry_store.list(notebook_id=nb_id)
        assert entries == []
