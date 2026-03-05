import asyncio
import json
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone

from odigos.core.heartbeat import Heartbeat
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


@pytest_asyncio.fixture
async def mock_agent():
    agent = MagicMock()
    agent.handle_message = AsyncMock(return_value="Task completed")
    return agent


@pytest_asyncio.fixture
async def mock_telegram():
    tg = MagicMock()
    tg.send_message = AsyncMock()
    return tg


@pytest_asyncio.fixture
async def heartbeat(db, mock_agent, mock_telegram, scheduler):
    return Heartbeat(
        db=db,
        agent=mock_agent,
        telegram_channel=mock_telegram,
        scheduler=scheduler,
        interval=0.1,
    )


@pytest.mark.asyncio
async def test_tick_executes_pending_task(heartbeat, scheduler, mock_agent, db):
    task_id = await scheduler.create(description="Say hello", delay_seconds=0)
    await heartbeat._tick()
    row = await db.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    assert row["status"] in ("completed", "failed")
    mock_agent.handle_message.assert_called_once()


@pytest.mark.asyncio
async def test_tick_skips_future_tasks(heartbeat, scheduler, mock_agent):
    await scheduler.create(description="Future task", delay_seconds=99999)
    await heartbeat._tick()
    mock_agent.handle_message.assert_not_called()


@pytest.mark.asyncio
async def test_tick_marks_completed(heartbeat, scheduler, db):
    task_id = await scheduler.create(description="Complete me")
    await heartbeat._tick()
    row = await db.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    assert row["status"] == "completed"
    assert row["completed_at"] is not None


@pytest.mark.asyncio
async def test_tick_handles_failure_and_retries(heartbeat, scheduler, mock_agent, db):
    mock_agent.handle_message = AsyncMock(side_effect=RuntimeError("boom"))
    task_id = await scheduler.create(description="Fail task")
    await heartbeat._tick()
    row = await db.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    assert row["status"] == "pending"
    assert row["retry_count"] == 1


@pytest.mark.asyncio
async def test_task_marked_failed_after_max_retries(heartbeat, scheduler, mock_agent, db):
    mock_agent.handle_message = AsyncMock(side_effect=RuntimeError("boom"))
    task_id = await scheduler.create(description="Always fails")
    for _ in range(4):
        await heartbeat._tick()
    row = await db.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    assert row["status"] == "failed"


@pytest.mark.asyncio
async def test_recurring_task_reinserts(heartbeat, scheduler, db):
    task_id = await scheduler.create(
        description="Recurring", recurrence_seconds=60
    )
    await heartbeat._tick()
    row = await db.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    assert row["status"] == "completed"
    pending = await scheduler.list_pending()
    assert len(pending) == 1
    assert pending[0]["id"] != task_id
    assert pending[0]["description"] == "Recurring"


@pytest.mark.asyncio
async def test_sends_telegram_message_on_completion(heartbeat, scheduler, mock_telegram, db):
    await db.execute(
        "INSERT INTO conversations (id, channel) VALUES (?, ?)",
        ("telegram:42", "telegram"),
    )
    await scheduler.create(
        description="Remind about meeting",
        conversation_id="telegram:42",
    )
    await heartbeat._tick()
    mock_telegram.send_message.assert_called_once()
    call_args = mock_telegram.send_message.call_args
    assert 42 == call_args[0][0]  # chat_id


@pytest.mark.asyncio
async def test_start_and_stop(heartbeat):
    await heartbeat.start()
    assert heartbeat._task is not None
    assert not heartbeat._task.done()
    await heartbeat.stop()
    await asyncio.sleep(0.05)
    assert heartbeat._task.cancelled() or heartbeat._task.done()


@pytest.mark.asyncio
async def test_max_tasks_per_tick(heartbeat, scheduler, mock_agent):
    heartbeat._max_tasks_per_tick = 2
    for i in range(5):
        await scheduler.create(description=f"Task {i}")
    await heartbeat._tick()
    assert mock_agent.handle_message.call_count == 2


@pytest.mark.asyncio
async def test_paused_heartbeat_skips_execution(heartbeat, scheduler, mock_agent):
    heartbeat.paused = True
    await scheduler.create(description="Should be skipped")
    await heartbeat._tick()
    mock_agent.handle_message.assert_not_called()
