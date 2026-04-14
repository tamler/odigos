import asyncio
import os
import sqlite3
import tempfile
from collections.abc import AsyncGenerator

import aiosqlite
import pytest
import pytest_asyncio

# Check once at import time whether sqlite3 supports extension loading
_test_conn = sqlite3.connect(":memory:")
try:
    _test_conn.enable_load_extension(True)
    HAS_SQLITE_VEC = True
except AttributeError:
    HAS_SQLITE_VEC = False
finally:
    _test_conn.close()

requires_sqlite_vec = pytest.mark.skipif(
    not HAS_SQLITE_VEC,
    reason="sqlite3 extension loading not supported in this Python build",
)

try:
    from odigos.config import Settings
except ImportError:
    Settings = None


@pytest.fixture(scope="session")
def event_loop_policy():
    return asyncio.DefaultEventLoopPolicy()


@pytest_asyncio.fixture
async def tmp_db_path() -> AsyncGenerator[str, None]:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    yield path
    os.unlink(path)


class FakeDB:
    """Minimal async database wrapper for tests."""

    def __init__(self, conn):
        self._conn = conn
        self._conn.row_factory = aiosqlite.Row

    async def execute(self, sql, params=()):
        cursor = await self._conn.execute(sql, params)
        await self._conn.commit()
        return cursor

    async def fetch_all(self, sql, params=()):
        cursor = await self._conn.execute(sql, params)
        return await cursor.fetchall()

    async def fetch_one(self, sql, params=()):
        cursor = await self._conn.execute(sql, params)
        return await cursor.fetchone()


@pytest_asyncio.fixture
async def fake_db():
    async with aiosqlite.connect(":memory:") as conn:
        conn.row_factory = aiosqlite.Row
        db = FakeDB(conn)
        await conn.execute("""
            CREATE TABLE query_log (
                id TEXT PRIMARY KEY,
                conversation_id TEXT,
                classification TEXT,
                tools_used TEXT,
                created_at TEXT
            )
        """)
        await conn.execute("""
            CREATE TABLE agent_experiences (
                id TEXT PRIMARY KEY,
                tool_name TEXT NOT NULL,
                situation TEXT NOT NULL,
                outcome TEXT NOT NULL,
                lesson TEXT NOT NULL,
                success INTEGER DEFAULT 1,
                times_applied INTEGER DEFAULT 0,
                confidence REAL DEFAULT 0.8,
                applicability TEXT DEFAULT 'sometimes',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        await conn.execute("""
            CREATE TABLE tasks (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                description TEXT,
                conversation_id TEXT,
                tool_name TEXT,
                external_task_id TEXT,
                arguments_json TEXT,
                result_json TEXT,
                error TEXT,
                retry_count INTEGER DEFAULT 0,
                max_retries INTEGER DEFAULT 3,
                created_at TEXT DEFAULT (datetime('now')),
                completed_at TEXT
            )
        """)
        await conn.execute("""
            CREATE TABLE conversations (
                id TEXT PRIMARY KEY,
                title TEXT,
                channel TEXT NOT NULL,
                status TEXT DEFAULT 'active',
                message_count INTEGER DEFAULT 0,
                last_message_at TEXT,
                category TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        await conn.execute("""
            CREATE TABLE messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL REFERENCES conversations(id),
                role TEXT NOT NULL,
                content TEXT,
                channel TEXT,
                message_type TEXT DEFAULT 'chat',
                model_used TEXT,
                tokens_in INTEGER,
                tokens_out INTEGER,
                cost_usd REAL,
                metadata_json TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        await conn.execute("""
            CREATE TABLE message_deliveries (
                id TEXT PRIMARY KEY,
                message_id TEXT NOT NULL REFERENCES messages(id),
                channel TEXT NOT NULL,
                delivered_at TEXT,
                seen_at TEXT
            )
        """)
        await conn.commit()
        yield db


if Settings is not None:

    @pytest.fixture
    def test_settings(tmp_db_path: str) -> Settings:
        return Settings(
            telegram_bot_token="test-token",
            searxng_url="https://search.example.com",
            searxng_username="testuser",
            searxng_password="testpass",
            agent={"name": "TestAgent"},
            database={"path": tmp_db_path},
            providers={
                "test": {
                    "base_url": "https://api.example.com/v1",
                    "api_key": "test-key",
                },
            },
            models={
                "test-fast": {"provider": "test", "id": "test/model"},
                "test-fallback": {"provider": "test", "id": "test/fallback"},
            },
            llm={
                "fast": "test-fast",
                "fallback": "test-fallback",
                "max_tokens": 100,
                "temperature": 0.5,
            },
            telegram={"mode": "polling", "webhook_url": ""},
            server={"host": "127.0.0.1", "port": 8000},
        )


def make_test_settings(**overrides):
    """Helper for tests that need a minimal Settings with provider/model plumbing."""
    from odigos.config import Settings
    defaults = {
        "providers": {
            "test": {"base_url": "https://api.example.com/v1", "api_key": "test-key"},
        },
        "models": {
            "test-fast": {"provider": "test", "id": "test/model"},
            "test-fallback": {"provider": "test", "id": "test/fallback"},
        },
        "llm": {"fast": "test-fast", "fallback": "test-fallback"},
    }
    defaults.update(overrides)
    return Settings(**defaults)
