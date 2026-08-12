"""Tests for the migration runner's error handling.

Charter 01-cleanup.md §0d. schema.sql creates every table in its current form
before migrations run, so any migration whose first statement is
`ALTER TABLE ... ADD COLUMN` hits "duplicate column name" on a current-schema
database. The runner used to hand the whole file to executescript(), which
aborts the entire script on the first failing statement -- so every remaining
statement in that file was silently skipped, and the failure was logged at
warning level and the migration marked applied.

Six migrations in this repo lead with such an ALTER (005, 008, 009, 010, 012,
015) and carry 1-12 further statements each, including the data backfills in
005 and 015.
"""
import tempfile
from pathlib import Path

import pytest

from odigos.db import Database


@pytest.fixture
def migrations_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def db_path():
    with tempfile.TemporaryDirectory() as d:
        yield str(Path(d) / "test.db")


async def test_statement_after_benign_duplicate_column_still_runs(migrations_dir, db_path):
    """A duplicate-column ALTER must not abort the rest of its migration file.

    users.session_epoch is already defined in schema.sql, so the ALTER below
    always fails. The CREATE TABLE after it must still be applied.
    """
    (migrations_dir / "900_probe.sql").write_text(
        "ALTER TABLE users ADD COLUMN session_epoch INTEGER NOT NULL DEFAULT 0;\n"
        "CREATE TABLE IF NOT EXISTS _migration_probe (id INTEGER PRIMARY KEY);\n"
    )

    db = Database(db_path, migrations_dir=str(migrations_dir))
    await db.initialize()
    try:
        row = await db.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='_migration_probe'"
        )
        assert row is not None, (
            "statement after the benign duplicate-column ALTER was skipped -- "
            "the whole migration file aborted on the first statement"
        )
    finally:
        await db.close()


async def test_data_backfill_after_duplicate_column_still_runs(migrations_dir, db_path):
    """The real shape of migrations 005 and 015: ALTER, then a backfill UPDATE."""
    (migrations_dir / "901_backfill.sql").write_text(
        "ALTER TABLE users ADD COLUMN session_epoch INTEGER NOT NULL DEFAULT 0;\n"
        "UPDATE users SET session_epoch = 99 WHERE session_epoch = 0;\n"
    )

    db = Database(db_path, migrations_dir=str(migrations_dir))
    await db.initialize()
    try:
        await db.execute(
            "INSERT INTO users (id, username, password_hash, created_at, session_epoch) "
            "VALUES (?, ?, ?, datetime('now'), ?)",
            ("u1", "probe", "x", 0),
        )
        # Re-run the migration chain against the now-populated table.
        await db.execute("DELETE FROM _migrations WHERE name = ?", ("901_backfill.sql",))
        await db.run_migrations()

        row = await db.fetch_one("SELECT session_epoch FROM users WHERE id = ?", ("u1",))
        assert row["session_epoch"] == 99, (
            "backfill UPDATE never ran -- it sat behind a failing ALTER in the same file"
        )
    finally:
        await db.close()


async def test_genuinely_broken_migration_raises(migrations_dir, db_path):
    """Real errors must surface, not be logged at warning and marked applied."""
    (migrations_dir / "902_broken.sql").write_text(
        "ALTER TABLE table_that_does_not_exist ADD COLUMN whatever TEXT;\n"
    )

    db = Database(db_path, migrations_dir=str(migrations_dir))
    with pytest.raises(Exception) as exc:
        await db.initialize()
    assert "902_broken.sql" in str(exc.value)
    await db.close()


async def test_failed_migration_leaves_no_partial_state(migrations_dir, db_path):
    """A migration that fails partway must roll back, not half-apply.

    It is also not recorded in _migrations, so it retries on next boot -- which
    would replay the succeeded statements if they had not been rolled back.
    """
    (migrations_dir / "903_partial.sql").write_text(
        "CREATE TABLE IF NOT EXISTS _partial_probe (id INTEGER PRIMARY KEY);\n"
        "ALTER TABLE table_that_does_not_exist ADD COLUMN whatever TEXT;\n"
    )

    db = Database(db_path, migrations_dir=str(migrations_dir))
    with pytest.raises(Exception):
        await db.initialize()
    try:
        row = await db.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='_partial_probe'"
        )
        assert row is None, "first statement stayed applied after the file failed"
        applied = await db.fetch_one(
            "SELECT name FROM _migrations WHERE name = ?", ("903_partial.sql",)
        )
        assert applied is None, "failed migration was recorded as applied"
    finally:
        await db.close()


async def test_migrations_are_rerunnable(migrations_dir, db_path):
    """Applying the real migration chain twice must not error."""
    repo_migrations = Path(__file__).parent.parent / "migrations"
    db = Database(db_path, migrations_dir=str(repo_migrations))
    await db.initialize()
    try:
        await db.execute("DELETE FROM _migrations")
        await db.run_migrations()
    finally:
        await db.close()
