from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from odigos.db import Database
from odigos.memory.ingester import DocumentIngester


@pytest_asyncio.fixture
async def db(tmp_db_path: str):
    database = Database(tmp_db_path, migrations_dir="migrations")
    await database.initialize()
    yield database
    await database.close()


@pytest.fixture
def mock_memory_store():
    ms = AsyncMock()
    ms.store = AsyncMock(return_value=str(uuid.uuid4()))
    return ms


@pytest.fixture
def mock_chunking():
    chunking = AsyncMock()
    chunking.chunk = lambda text, content_type="document": [text] if text else []
    return chunking


@pytest.fixture
def ingester(db, mock_memory_store, mock_chunking):
    return DocumentIngester(
        db=db,
        memory_store=mock_memory_store,
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
        self, ingester, db,
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

    async def test_ingest_exact_duplicate_skipped(
        self, ingester, db, mock_memory_store,
    ):
        first_id = await ingester.ingest(
            text="Same content",
            filename="readme.txt",
            content_hash="deadbeef",
        )

        mock_memory_store.store.reset_mock()

        second_id = await ingester.ingest(
            text="Same content",
            filename="readme.txt",
            content_hash="deadbeef",
        )

        assert first_id == second_id
        # No new chunks should have been stored
        mock_memory_store.store.assert_not_called()

        # Only one document row in the DB
        rows = await db.fetch_all(
            "SELECT id FROM documents WHERE filename = ?", ("readme.txt",),
        )
        assert len(rows) == 1

    async def test_ingest_sets_status_failed_on_error(
        self, ingester, db, mock_memory_store,
    ):
        mock_memory_store.store = AsyncMock(
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
