import pytest

from odigos.db import Database


@pytest.fixture
async def db(tmp_db_path: str) -> Database:
    database = Database(tmp_db_path, migrations_dir="migrations")
    await database.initialize()
    yield database
    await database.close()


async def test_migrations_applied(db: Database):
    """Migrations create the expected tables."""
    tables = await db.fetch_all(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    table_names = [row["name"] for row in tables]
    assert "conversations" in table_names
    assert "messages" in table_names
    assert "_migrations" in table_names


async def test_migrations_idempotent(db: Database):
    """Running migrations twice doesn't error."""
    await db.run_migrations()
    tables = await db.fetch_all(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    table_names = [row["name"] for row in tables]
    assert "conversations" in table_names


async def test_execute_and_fetch(db: Database):
    """Basic insert and query works."""
    await db.execute(
        "INSERT INTO conversations (id, channel) VALUES (?, ?)",
        ("conv-1", "telegram"),
    )
    row = await db.fetch_one(
        "SELECT id, channel FROM conversations WHERE id = ?", ("conv-1",)
    )
    assert row is not None
    assert row["id"] == "conv-1"
    assert row["channel"] == "telegram"


async def test_fetch_all(db: Database):
    """fetch_all returns multiple rows."""
    await db.execute(
        "INSERT INTO conversations (id, channel) VALUES (?, ?)",
        ("conv-1", "telegram"),
    )
    await db.execute(
        "INSERT INTO conversations (id, channel) VALUES (?, ?)",
        ("conv-2", "email"),
    )
    rows = await db.fetch_all("SELECT id FROM conversations ORDER BY id")
    assert len(rows) == 2
    assert rows[0]["id"] == "conv-1"
    assert rows[1]["id"] == "conv-2"


async def test_fetch_one_returns_none(db: Database):
    """fetch_one returns None when no rows match."""
    row = await db.fetch_one(
        "SELECT id FROM conversations WHERE id = ?", ("nonexistent",)
    )
    assert row is None


async def test_sqlite_vec_extension_loaded(tmp_db_path: str):
    """Verify sqlite-vec extension is loaded and vec0 is available."""
    db = Database(tmp_db_path, migrations_dir="migrations")
    await db.initialize()
    try:
        # sqlite-vec registers a vec_version() function
        row = await db.fetch_one("SELECT vec_version() AS v")
        assert row is not None
        assert row["v"]  # non-empty version string
    finally:
        await db.close()
