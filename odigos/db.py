from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite
import sqlite_vec

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_DELAYS = (0.1, 0.2, 0.4)  # seconds


def _is_busy_error(e: Exception) -> bool:
    msg = str(e).lower()
    return "locked" in msg or "busy" in msg


async def _retry_on_busy(coro_factory, max_retries=_MAX_RETRIES):
    """Retry a coroutine factory on SQLITE_BUSY with exponential backoff."""
    for attempt in range(max_retries + 1):
        try:
            return await coro_factory()
        except aiosqlite.OperationalError as e:
            if not _is_busy_error(e):
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
        migrations_path = Path(migrations_dir)
        # If relative and doesn't exist in CWD, try relative to package root
        if not migrations_path.is_absolute() and not migrations_path.exists():
            package_root = Path(__file__).parent.parent
            alt = package_root / migrations_dir
            if alt.exists():
                migrations_path = alt
        self.migrations_dir = migrations_path
        self._conn: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Open connection and run migrations."""
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._conn.execute("PRAGMA synchronous=NORMAL")
        await self._conn.execute("PRAGMA cache_size=-64000")

        # Load sqlite-vec extension for vector search
        self._vec_loaded = False
        try:
            await self._conn.enable_load_extension(True)
            await self._conn.load_extension(sqlite_vec.loadable_path())
            await self._conn.enable_load_extension(False)
            self._vec_loaded = True
        except AttributeError:
            logger.warning("sqlite3 extension loading not supported in this Python build")

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
            if not self._vec_loaded and "vec0" in sql:
                # Strip vec0 virtual table creation so the rest of the migration runs
                import re
                filtered = re.sub(
                    r"CREATE\s+VIRTUAL\s+TABLE[^;]*USING\s+vec0\([^)]*\)\s*;",
                    "-- (vec0 table skipped, extension not loaded)",
                    sql,
                    flags=re.IGNORECASE | re.DOTALL,
                )
                try:
                    await self.conn.executescript(filtered)
                except Exception as e:
                    logger.warning("Migration %s partially failed: %s", migration_file.name, e)
            else:
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

    @asynccontextmanager
    async def transaction(self):
        """Async context manager for atomic multi-statement transactions.

        Uses BEGIN IMMEDIATE to acquire a write lock upfront, preventing
        deadlocks under WAL mode. Commits on clean exit, rolls back on
        any exception.

        Usage:
            async with db.transaction() as tx:
                await tx.execute("INSERT ...", params)
                await tx.execute("UPDATE ...", params)

        For BUSY retry of entire transaction blocks, use run_transaction().
        """
        await self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
        except Exception:
            await self.conn.rollback()
            raise
        else:
            await self.conn.commit()

    async def run_transaction(self, fn, max_retries: int = _MAX_RETRIES):
        """Execute a callable as an atomic transaction with BUSY retry.

        The callable receives the raw connection and can execute multiple
        statements. On BUSY/locked errors, the entire transaction (rollback
        + re-execute) is retried with exponential backoff.

        Usage:
            async def do_work(conn):
                await conn.execute("INSERT ...", params)
                await conn.execute("UPDATE ...", params)
            await db.run_transaction(do_work)
        """
        async def _do():
            await self.conn.execute("BEGIN IMMEDIATE")
            try:
                result = await fn(self.conn)
                await self.conn.commit()
                return result
            except Exception:
                try:
                    await self.conn.rollback()
                except Exception:
                    pass
                raise
        return await _retry_on_busy(_do, max_retries=max_retries)

    async def execute_in_transaction(self, statements: list[tuple[str, tuple]]) -> None:
        """Execute multiple statements atomically in a single transaction."""
        async def _do():
            await self.conn.execute("BEGIN")
            try:
                for sql, params in statements:
                    await self.conn.execute(sql, params)
                await self.conn.commit()
            except Exception:
                await self.conn.rollback()
                raise
        await _retry_on_busy(_do)
