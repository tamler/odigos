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
