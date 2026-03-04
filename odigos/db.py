from pathlib import Path

import aiosqlite


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
            row[0]
            for row in await self.conn.execute_fetchall(
                "SELECT name FROM _migrations"
            )
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
        await self.conn.execute(sql, params)
        await self.conn.commit()

    async def fetch_one(self, sql: str, params: tuple = ()) -> dict | None:
        """Fetch a single row as a dict, or None."""
        cursor = await self.conn.execute(sql, params)
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    async def fetch_all(self, sql: str, params: tuple = ()) -> list[dict]:
        """Fetch all rows as a list of dicts."""
        cursor = await self.conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
