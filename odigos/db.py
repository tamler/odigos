from __future__ import annotations

import asyncio
import logging
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite
import sqlite_vec

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_DELAYS = (0.1, 0.2, 0.4)  # seconds

# The one migration failure that is expected rather than broken. schema.sql
# creates every table in its current form before migrations run, so a migration
# that adds a column schema.sql already declares will always raise this.
_BENIGN_MIGRATION_ERRORS = ("duplicate column name",)


class MigrationError(RuntimeError):
    """A migration statement failed for a reason that is not benign."""


def _is_benign_migration_error(e: Exception) -> bool:
    msg = str(e).lower()
    return any(token in msg for token in _BENIGN_MIGRATION_ERRORS)


def _is_comment_only(statement: str) -> bool:
    for line in statement.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("--"):
            return False
    return True


def _split_sql_statements(script: str) -> list[str]:
    """Split a SQL script into individually executable statements.

    Uses sqlite3.complete_statement -- the same check the sqlite3 CLI uses to
    decide whether to keep reading -- so semicolons inside string literals and
    inside CREATE TRIGGER ... BEGIN ... END; blocks do not split incorrectly,
    which a naive split(";") would get wrong.

    Completeness is tested at every semicolon rather than at line boundaries,
    so two statements written on one line split correctly. sqlite3.execute()
    accepts exactly one statement, so getting this wrong would turn an ordinary
    formatting choice by a future migration author into a boot failure.
    """
    statements: list[str] = []
    start = 0
    for i, ch in enumerate(script):
        if ch != ";":
            continue
        candidate = script[start:i + 1]
        if sqlite3.complete_statement(candidate):
            statements.append(candidate)
            start = i + 1
    tail = script[start:]
    if tail.strip():
        statements.append(tail)
    return [s for s in statements if not _is_comment_only(s)]


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

        # Ensure base schema exists (creates all tables on fresh databases)
        await self._ensure_schema()
        # Evolve existing tables — add missing columns from schema.sql
        await self._evolve_schema()
        await self.run_migrations()

        # Check if DB is empty but brain files exist — trigger rebuild
        await self._maybe_rebuild_from_brain()

    async def _maybe_rebuild_from_brain(self) -> None:
        """If DB has no entities but data/brain/ has files, rebuild from brain."""
        from pathlib import Path
        brain_dir = Path("data/brain")
        if not brain_dir.exists():
            return

        # Check if DB already has data
        try:
            row = await self.fetch_one("SELECT COUNT(*) as cnt FROM entities")
            if row and row["cnt"] > 0:
                return
        except Exception:
            return  # Table might not exist yet

        # Check if brain has content
        entity_files = list(brain_dir.glob("entities/*.md"))
        topic_files = list(brain_dir.glob("topics/*.md"))
        if not entity_files and not topic_files:
            return

        logger.info("Empty DB with existing brain files — rebuilding from brain...")
        try:
            from odigos.memory.brain_reader import rebuild_from_brain
            stats = await rebuild_from_brain(self, brain_dir)
            logger.info("Brain rebuild complete: %s", stats)
        except Exception:
            logger.exception("Brain rebuild failed")

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

    async def _ensure_schema(self) -> None:
        """Run schema.sql to ensure all tables exist.

        Uses IF NOT EXISTS so it's safe on existing databases.
        Runs before migrations so fresh databases get the full schema
        without needing to replay 50+ migration files.
        """
        schema_path = Path(__file__).parent.parent / "schema.sql"
        if not schema_path.exists():
            return
        sql = schema_path.read_text()
        # Strip vec0 tables if extension not loaded
        if not self._vec_loaded and "vec0" in sql:
            import re
            sql = re.sub(
                r"CREATE\s+VIRTUAL\s+TABLE[^;]*USING\s+vec0\([^)]*\)\s*;",
                "-- (vec0 table skipped, extension not loaded)",
                sql,
                flags=re.IGNORECASE | re.DOTALL,
            )
        try:
            await self.conn.executescript(sql)
        except Exception as e:
            # executescript stops at the first error — re-run individual CREATE TABLE
            # statements so one failure (e.g., vec0) doesn't skip critical tables.
            logger.warning("Schema executescript partial failure: %s — retrying individual statements", e)
            for statement in sql.split(";"):
                s = statement.strip()
                if not s or s.startswith("--"):
                    continue
                if not s.upper().startswith(("CREATE ", "INSERT ")):
                    continue
                try:
                    await self.conn.execute(s)
                except Exception:
                    pass  # Already exists or unsupported — skip
            await self.conn.commit()

    async def _evolve_schema(self) -> None:
        """Add missing columns to existing tables by comparing schema.sql to live DB.

        schema.sql defines the canonical schema. On existing databases, CREATE TABLE
        IF NOT EXISTS won't add new columns. This method diffs schema.sql against
        PRAGMA table_info() and runs ALTER TABLE ADD COLUMN for any missing columns.
        """
        import re
        schema_path = Path(__file__).parent.parent / "schema.sql"
        if not schema_path.exists():
            return
        sql = schema_path.read_text()

        # Parse CREATE TABLE statements from schema.sql
        table_pattern = re.compile(
            r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s*\((.*?)\);",
            re.IGNORECASE | re.DOTALL,
        )
        for match in table_pattern.finditer(sql):
            table_name = match.group(1)
            body = match.group(2)

            # Skip virtual tables, internal tables
            if table_name.startswith("_"):
                continue

            # Get existing columns from live DB
            try:
                rows = await self.conn.execute_fetchall(f"PRAGMA table_info({table_name})")
            except Exception:
                continue  # Table doesn't exist yet — _ensure_schema will create it
            existing_cols = {row[1] for row in rows}  # row[1] is column name

            # Parse columns from schema.sql body
            for line in body.split(","):
                line = line.strip()
                if not line or line.upper().startswith(("PRIMARY KEY", "FOREIGN KEY", "UNIQUE", "CHECK")):
                    continue
                parts = line.split()
                if not parts:
                    continue
                col_name = parts[0].strip('"')
                if col_name.upper() in ("PRIMARY", "FOREIGN", "UNIQUE", "CHECK", "CONSTRAINT"):
                    continue

                if col_name not in existing_cols:
                    # Build ALTER TABLE statement
                    col_def = line.rstrip(",").strip()
                    try:
                        await self.conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {col_def}")
                        logger.info("Schema evolution: added %s.%s", table_name, col_name)
                    except Exception as e:
                        logger.debug("Schema evolution skip %s.%s: %s", table_name, col_name, e)

        await self.conn.commit()

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
                sql = re.sub(
                    r"CREATE\s+VIRTUAL\s+TABLE[^;]*USING\s+vec0\([^)]*\)\s*;",
                    "-- (vec0 table skipped, extension not loaded)",
                    sql,
                    flags=re.IGNORECASE | re.DOTALL,
                )
            await self._apply_migration(migration_file.name, sql)
            await self.conn.execute(
                "INSERT INTO _migrations (name) VALUES (?)",
                (migration_file.name,),
            )
            await self.conn.commit()

    async def _apply_migration(self, name: str, sql: str) -> None:
        """Apply one migration file, one statement at a time.

        Statement-at-a-time rather than executescript(). schema.sql creates
        every table in its current form before migrations run, so any migration
        leading with `ALTER TABLE ... ADD COLUMN` raises "duplicate column name"
        on a current database. executescript() aborts the entire file at that
        point, which silently dropped every later statement -- in this repo that
        is six migrations (005, 008, 009, 010, 012, 015) carrying up to twelve
        further statements each, including the data backfills in 005 and 015.

        A duplicate-column error is the one expected outcome and is skipped.
        Anything else is a real failure and is raised rather than logged and
        marked applied.
        """
        await self.conn.execute("SAVEPOINT odigos_migration")
        try:
            for statement in _split_sql_statements(sql):
                try:
                    # _retry_on_busy so a transient SQLITE_BUSY during startup
                    # is retried rather than raised as a migration failure.
                    await _retry_on_busy(lambda s=statement: self.conn.execute(s))
                except Exception as e:
                    if _is_benign_migration_error(e):
                        logger.debug(
                            "Migration %s: %s -- already present in schema.sql, statement skipped",
                            name, e,
                        )
                        continue
                    raise MigrationError(
                        f"Migration {name} failed on statement: {statement.strip()[:150]}"
                    ) from e
        except Exception:
            # All-or-nothing per file: a migration that fails partway is not
            # recorded as applied, so it will be retried on the next boot.
            # Without the rollback that retry would replay statements that had
            # already succeeded.
            await self.conn.execute("ROLLBACK TO odigos_migration")
            await self.conn.execute("RELEASE odigos_migration")
            raise
        await self.conn.execute("RELEASE odigos_migration")

    async def execute(self, sql: str, params: tuple = ()) -> None:
        """Execute a single SQL statement."""
        async def _do():
            await self.conn.execute(sql, params)
            await self.conn.commit()
        await _retry_on_busy(_do)

    async def execute_returning_rowcount(self, sql: str, params: tuple = ()) -> int:
        """Execute a statement and return how many rows it affected.

        execute() returns None, so callers that needed a count were silently
        getting zero -- see agent_client.mark_stale_peers.
        """
        result = 0
        async def _do():
            nonlocal result
            cursor = await self.conn.execute(sql, params)
            await self.conn.commit()
            result = cursor.rowcount if cursor.rowcount is not None else 0
        await _retry_on_busy(_do)
        return result

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
