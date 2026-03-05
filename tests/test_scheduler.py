import pytest
import pytest_asyncio
from odigos.core.scheduler import TaskScheduler
from odigos.db import Database


@pytest_asyncio.fixture
async def db(tmp_db_path):
    d = Database(tmp_db_path)
    await d.initialize()
    yield d
    await d.close()


@pytest_asyncio.fixture
async def scheduler(db):
    return TaskScheduler(db=db)


@pytest.mark.asyncio
async def test_create_one_shot_task(scheduler, db):
    task_id = await scheduler.create(description="Say hello")
    row = await db.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    assert row is not None
    assert row["type"] == "one_shot"
    assert row["status"] == "pending"
    assert row["description"] == "Say hello"
    assert row["scheduled_at"] is not None


@pytest.mark.asyncio
async def test_create_delayed_task(scheduler, db):
    task_id = await scheduler.create(description="Remind me", delay_seconds=3600)
    row = await db.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    assert row is not None
    assert row["scheduled_at"] is not None


@pytest.mark.asyncio
async def test_create_recurring_task(scheduler, db):
    task_id = await scheduler.create(
        description="Check email", recurrence_seconds=1800
    )
    row = await db.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    assert row["type"] == "recurring"
    assert '"interval_seconds": 1800' in row["recurrence_json"]


@pytest.mark.asyncio
async def test_cancel_task(scheduler, db):
    task_id = await scheduler.create(description="Cancel me")
    result = await scheduler.cancel(task_id)
    assert result is True
    row = await db.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    assert row["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_nonexistent_returns_false(scheduler):
    result = await scheduler.cancel("nonexistent-id")
    assert result is False


@pytest.mark.asyncio
async def test_list_pending(scheduler):
    await scheduler.create(description="Task A")
    await scheduler.create(description="Task B", delay_seconds=99999)
    tasks = await scheduler.list_pending()
    assert len(tasks) == 2


@pytest.mark.asyncio
async def test_get_task(scheduler):
    task_id = await scheduler.create(description="Get me")
    task = await scheduler.get(task_id)
    assert task is not None
    assert task["description"] == "Get me"


@pytest.mark.asyncio
async def test_get_nonexistent_returns_none(scheduler):
    task = await scheduler.get("nonexistent-id")
    assert task is None


@pytest.mark.asyncio
async def test_create_with_priority(scheduler, db):
    task_id = await scheduler.create(description="Urgent", priority=0)
    row = await db.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    assert row["priority"] == 0


@pytest.mark.asyncio
async def test_create_with_conversation_id(scheduler, db):
    task_id = await scheduler.create(
        description="Reply", conversation_id="telegram:12345"
    )
    row = await db.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    assert row["conversation_id"] == "telegram:12345"
