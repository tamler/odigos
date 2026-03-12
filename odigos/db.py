from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import aiosqlite
import sqlite_vec

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_DELAYS = (0.1, 0.2, 0.4)  # seconds


async def _retry_on_busy(coro_factory, max_retries=_MAX_RETRIES):
    """Retry a coroutine factory on SQLITE_BUSY with exponential backoff."""
    for attempt in range(max_retries + 1):
        try:
            return await coro_factory()
        except aiosqlite.OperationalError as e:
            if "locked" not in str(e).lower() and "busy" not in str(e).lower():
                raise
            if attempt >= max_retries:
                raise
            delay = _RETRY_DELAYS[attempt] if attempt < len(_RETRY_DELAYS) else _RETRY_DELAYS[-1]
            logger.warning("DB busy, retrying in %.1fs (attempt %d/%d)", delay, attempt + 1, max_retries)
            await asyncio.sleep(delay)


class Database:
    """Async SQLite helper with migration support."""

    def __init__(self, db_path: str, migrations_dir: str = "migrations") -> None:
        self.db_path = db_path
        self.migrations_dir = Path(migrations_dir)
        self._conn: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Open connection and run migrations."""
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")

        # Load sqlite-vec extension for vector search
        await self._conn.enable_load_extension(True)
        await self._conn.load_extension(sqlite_vec.loadable_path())
        await self._conn.enable_load_extension(False)

        await self.run_migrations()

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        return self._conn

    async def run_migrations(self) -> None:
        """Apply SQL migration files in order, tracking which have been applied."""
        await self.conn.execute(
            "CREATE TABLE IF NOT EXISTS _migrations ("
            "  name TEXT PRIMARY KEY,"
            "  applied_at TEXT DEFAULT (datetime('now'))"
            ")"
        )
        await self.conn.commit()

        applied = {
            row[0] for row in await self.conn.execute_fetchall("SELECT name FROM _migrations")
        }

        if not self.migrations_dir.exists():
            return

        migration_files = sorted(self.migrations_dir.glob("*.sql"))
        for migration_file in migration_files:
            if migration_file.name in applied:
                continue
            sql = migration_file.read_text()
            await self.conn.executescript(sql)
            await self.conn.execute(
                "INSERT INTO _migrations (name) VALUES (?)",
                (migration_file.name,),
            )
            await self.conn.commit()

    async def execute(self, sql: str, params: tuple = ()) -> None:
        """Execute a single SQL statement."""
        async def _do():
            await self.conn.execute(sql, params)
            await self.conn.commit()
        await _retry_on_busy(_do)

    async def execute_returning_lastrowid(self, sql: str, params: tuple = ()) -> int:
        """Execute a single SQL statement and return lastrowid (for INSERT)."""
        result = None
        async def _do():
            nonlocal result
            cursor = await self.conn.execute(sql, params)
            await self.conn.commit()
            result = cursor.lastrowid
        await _retry_on_busy(_do)
        return result

    async def fetch_one(self, sql: str, params: tuple = ()) -> dict | None:
        """Fetch a single row as a dict, or None."""
        result = None
        async def _do():
            nonlocal result
            cursor = await self.conn.execute(sql, params)
            row = await cursor.fetchone()
            result = dict(row) if row else None
        await _retry_on_busy(_do)
        return result

    async def fetch_all(self, sql: str, params: tuple = ()) -> list[dict]:
        """Fetch all rows as a list of dicts."""
        result = []
        async def _do():
            nonlocal result
            cursor = await self.conn.execute(sql, params)
            rows = await cursor.fetchall()
            result = [dict(row) for row in rows]
        await _retry_on_busy(_do)
        return result

    async def execute_in_transaction(self, statements: list[tuple[str, tuple]]) -> None:
        """Execute multiple statements atomically in a single transaction."""
        await self.conn.execute("BEGIN")
        try:
            for sql, params in statements:
                await self.conn.execute(sql, params)
            await self.conn.commit()
        except Exception:
            await self.conn.rollback()
            raise
