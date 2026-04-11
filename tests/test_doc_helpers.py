from __future__ import annotations

import ast
import json
import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from odigos.db import Database
from odigos.memory.ingester import DocumentIngester
from odigos.tools.doc_helpers import prepare_doc_files, DOC_PREAMBLE


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


@pytest_asyncio.fixture
async def db_with_docs(db, mock_memory_store, mock_chunking):
    ingester = DocumentIngester(
        db=db,
        memory_store=mock_memory_store,
        chunking_service=mock_chunking,
    )
    await ingester.ingest(
        text="Sherlock Holmes visited Trafalgar Square on a foggy morning.",
        filename="sherlock.txt",
    )
    await ingester.ingest(
        text="Watson kept detailed notes about Baker Street.",
        filename="watson.txt",
    )
    return db


def test_preamble_valid_python():
    ast.parse(DOC_PREAMBLE)


@pytest.mark.asyncio
async def test_prepare_creates_index(db_with_docs):
    files, has_docs = await prepare_doc_files(db_with_docs)
    assert has_docs is True
    assert "docs/index.json" in files
    index = json.loads(files["docs/index.json"])
    assert len(index) == 2


@pytest.mark.asyncio
async def test_prepare_loads_small_docs(db_with_docs):
    files, has_docs = await prepare_doc_files(db_with_docs)
    txt_files = [k for k in files if k.endswith(".txt")]
    assert len(txt_files) == 2
    contents = [files[k] for k in txt_files]
    assert any("Trafalgar Square" in c for c in contents)


@pytest.mark.asyncio
async def test_prepare_no_docs(tmp_path):
    db = Database(str(tmp_path / "empty.db"), migrations_dir="migrations")
    await db.initialize()
    try:
        files, has_docs = await prepare_doc_files(db)
        assert has_docs is False
        assert files == {}
    finally:
        await db.close()
