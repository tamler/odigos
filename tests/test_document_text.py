from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import aiosqlite
import pytest
import pytest_asyncio

from odigos.db import Database
from odigos.memory.ingester import DocumentIngester


async def _make_test_db(path: str) -> Database:
    """Create a Database with SQL migrations applied (no sqlite-vec)."""
    db = Database(path, migrations_dir="migrations")
    db._conn = await aiosqlite.connect(path)
    db._conn.row_factory = aiosqlite.Row
    await db._conn.execute("PRAGMA journal_mode=WAL")
    await db._conn.execute("PRAGMA foreign_keys=ON")

    await db.conn.execute(
        "CREATE TABLE IF NOT EXISTS _migrations ("
        "  name TEXT PRIMARY KEY,"
        "  applied_at TEXT DEFAULT (datetime('now'))"
        ")"
    )
    await db.conn.commit()

    from pathlib import Path

    migrations_dir = Path("migrations")
    if migrations_dir.exists():
        for mf in sorted(migrations_dir.glob("*.sql")):
            sql = mf.read_text()
            if "vec0" in sql.lower():
                continue
            try:
                await db.conn.executescript(sql)
            except Exception:
                continue
            await db.conn.execute(
                "INSERT OR IGNORE INTO _migrations (name) VALUES (?)",
                (mf.name,),
            )
            await db.conn.commit()

    return db


@pytest_asyncio.fixture
async def db(tmp_db_path: str):
    database = await _make_test_db(tmp_db_path)
    yield database
    await database.close()


@pytest.fixture
def mock_vector_memory():
    vm = AsyncMock()
    vm.store = AsyncMock(return_value=str(uuid.uuid4()))
    vm.delete_by_source = AsyncMock()
    return vm


@pytest.fixture
def mock_chunking():
    chunking = AsyncMock()
    chunking.chunk = lambda text, content_type="document": [text] if text else []
    return chunking


@pytest.fixture
def ingester(db, mock_vector_memory, mock_chunking):
    return DocumentIngester(
        db=db,
        vector_memory=mock_vector_memory,
        chunking_service=mock_chunking,
    )


class TestDocumentText:
    async def test_full_text_stored_on_ingest(self, ingester, db):
        text = "The quick brown fox jumps over the lazy dog."
        doc_id = await ingester.ingest(text=text, filename="fox.txt")

        row = await db.fetch_one(
            "SELECT full_text FROM document_text WHERE document_id = ?",
            (doc_id,),
        )
        assert row is not None
        assert row["full_text"] == text

    async def test_full_text_deleted_on_cascade(self, ingester, db):
        doc_id = await ingester.ingest(
            text="Temporary content", filename="temp.txt",
        )

        # Verify it exists first
        row = await db.fetch_one(
            "SELECT full_text FROM document_text WHERE document_id = ?",
            (doc_id,),
        )
        assert row is not None

        # Delete via the documents table; CASCADE should remove document_text row
        await db.execute("DELETE FROM documents WHERE id = ?", (doc_id,))

        row = await db.fetch_one(
            "SELECT full_text FROM document_text WHERE document_id = ?",
            (doc_id,),
        )
        assert row is None

    async def test_reingest_updates_full_text(self, ingester, db):
        original_text = "Version 1 of the document."
        doc_id_v1 = await ingester.ingest(
            text=original_text,
            filename="evolving.txt",
            content_hash="hash_v1",
        )

        row = await db.fetch_one(
            "SELECT full_text FROM document_text WHERE document_id = ?",
            (doc_id_v1,),
        )
        assert row["full_text"] == original_text

        updated_text = "Version 2 with new content."
        doc_id_v2 = await ingester.ingest(
            text=updated_text,
            filename="evolving.txt",
            content_hash="hash_v2",
            force=True,
        )

        # Old document_text row should be gone (cascade from delete)
        old_row = await db.fetch_one(
            "SELECT full_text FROM document_text WHERE document_id = ?",
            (doc_id_v1,),
        )
        assert old_row is None

        # New document_text row should have updated text
        new_row = await db.fetch_one(
            "SELECT full_text FROM document_text WHERE document_id = ?",
            (doc_id_v2,),
        )
        assert new_row is not None
        assert new_row["full_text"] == updated_text
