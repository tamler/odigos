from __future__ import annotations

import ast
import json
import uuid
from unittest.mock import AsyncMock

import aiosqlite
import pytest
import pytest_asyncio

from odigos.db import Database
from odigos.memory.ingester import DocumentIngester
from odigos.tools.doc_helpers import prepare_doc_files, DOC_PREAMBLE


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


@pytest_asyncio.fixture
async def db_with_docs(db, mock_vector_memory, mock_chunking):
    ingester = DocumentIngester(
        db=db,
        vector_memory=mock_vector_memory,
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
    db = await _make_test_db(str(tmp_path / "empty.db"))
    try:
        files, has_docs = await prepare_doc_files(db)
        assert has_docs is False
        assert files == {}
    finally:
        await db.close()
