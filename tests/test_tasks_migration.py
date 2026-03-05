import pytest
import pytest_asyncio
from odigos.db import Database


@pytest_asyncio.fixture
async def db(tmp_db_path):
    d = Database(tmp_db_path)
    await d.initialize()
    yield d
    await d.close()


@pytest.mark.asyncio
async def test_tasks_table_exists(db):
    result = await db.fetch_one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'"
    )
    assert result is not None
    assert result["name"] == "tasks"


@pytest.mark.asyncio
async def test_tasks_table_columns(db):
    rows = await db.fetch_all("PRAGMA table_info(tasks)")
    columns = {row["name"] for row in rows}
    expected = {
        "id", "type", "status", "description", "payload_json",
        "scheduled_at", "started_at", "completed_at", "result_json",
        "error", "retry_count", "max_retries", "priority",
        "recurrence_json", "conversation_id", "created_by",
    }
    assert expected.issubset(columns)


@pytest.mark.asyncio
async def test_tasks_insert_and_query(db):
    await db.execute(
        "INSERT INTO tasks (id, type, description) VALUES (?, ?, ?)",
        ("t1", "one_shot", "Test task"),
    )
    row = await db.fetch_one("SELECT * FROM tasks WHERE id = ?", ("t1",))
    assert row is not None
    assert row["status"] == "pending"
    assert row["priority"] == 1
    assert row["retry_count"] == 0
    assert row["max_retries"] == 3
