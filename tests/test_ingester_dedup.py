from __future__ import annotations

import tempfile
import uuid
from unittest.mock import AsyncMock

import aiosqlite
import pytest
import pytest_asyncio

from odigos.db import Database
from odigos.memory.ingester import DocumentIngester


async def _make_test_db(path: str) -> Database:
    """Create a Database with only the SQL migrations applied (no sqlite-vec).

    The system Python's sqlite3 does not support enable_load_extension, so we
    bypass Database.initialize() and apply migrations manually via
    executescript, skipping any that reference vec0 or sqlite_vec virtual
    tables.
    """
    db = Database(path, migrations_dir="migrations")
    db._conn = await aiosqlite.connect(path)
    db._conn.row_factory = aiosqlite.Row
    await db._conn.execute("PRAGMA journal_mode=WAL")
    await db._conn.execute("PRAGMA foreign_keys=ON")

    # Apply migrations, skipping vector-specific ones
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
            # Skip migrations that create vec0 virtual tables
            if "vec0" in sql.lower():
                continue
            try:
                await db.conn.executescript(sql)
            except Exception:
                # Skip migrations that fail without sqlite-vec
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


class TestIngesterDedup:
    async def test_ingest_creates_document_with_provenance(self, ingester, db):
        doc_id = await ingester.ingest(
            text="Hello world",
            filename="notes.txt",
            source_url="https://example.com/notes.txt",
            file_path="/uploads/notes.txt",
            file_size=11,
            content_hash="abc123",
            conversation_id="conv-42",
        )

        row = await db.fetch_one("SELECT * FROM documents WHERE id = ?", (doc_id,))
        assert row is not None
        assert row["filename"] == "notes.txt"
        assert row["source_url"] == "https://example.com/notes.txt"
        assert row["file_path"] == "/uploads/notes.txt"
        assert row["file_size"] == 11
        assert row["content_hash"] == "abc123"
        assert row["conversation_id"] == "conv-42"
        assert row["status"] == "ingested"
        assert row["chunk_count"] == 1

    async def test_ingest_deduplicates_by_filename(
        self, ingester, db, mock_vector_memory,
    ):
        first_id = await ingester.ingest(
            text="Version 1",
            filename="report.txt",
            content_hash="hash_v1",
        )

        second_id = await ingester.ingest(
            text="Version 2",
            filename="report.txt",
            content_hash="hash_v2",
        )

        assert first_id != second_id

        # Old document should be gone
        old_row = await db.fetch_one(
            "SELECT id FROM documents WHERE id = ?", (first_id,),
        )
        assert old_row is None

        # New document should exist
        new_row = await db.fetch_one(
            "SELECT * FROM documents WHERE id = ?", (second_id,),
        )
        assert new_row is not None
        assert new_row["content_hash"] == "hash_v2"
        assert new_row["status"] == "ingested"

        # Old chunks should have been deleted via vector_memory
        mock_vector_memory.delete_by_source.assert_called_with(
            "document_chunk", first_id,
        )

    async def test_ingest_exact_duplicate_skipped(
        self, ingester, db, mock_vector_memory,
    ):
        first_id = await ingester.ingest(
            text="Same content",
            filename="readme.txt",
            content_hash="deadbeef",
        )

        mock_vector_memory.store.reset_mock()

        second_id = await ingester.ingest(
            text="Same content",
            filename="readme.txt",
            content_hash="deadbeef",
        )

        assert first_id == second_id
        # No new chunks should have been stored
        mock_vector_memory.store.assert_not_called()

        # Only one document row in the DB
        rows = await db.fetch_all(
            "SELECT id FROM documents WHERE filename = ?", ("readme.txt",),
        )
        assert len(rows) == 1

    async def test_ingest_sets_status_failed_on_error(
        self, ingester, db, mock_vector_memory,
    ):
        mock_vector_memory.store = AsyncMock(
            side_effect=RuntimeError("embedding service down"),
        )

        doc_id = await ingester.ingest(
            text="This will fail to embed",
            filename="fail.txt",
            content_hash="fail_hash",
        )

        row = await db.fetch_one(
            "SELECT status, chunk_count FROM documents WHERE id = ?", (doc_id,),
        )
        assert row is not None
        assert row["status"] == "failed"
        assert row["chunk_count"] == 0
