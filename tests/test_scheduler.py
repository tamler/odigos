"""Tests for the unified Scheduler."""
import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone

from odigos.core.scheduler import Scheduler
from odigos.db import Database


@pytest_asyncio.fixture
async def db(tmp_db_path):
    d = Database(tmp_db_path, migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


@pytest_asyncio.fixture
async def scheduler(db):
    return Scheduler(db=db)


async def test_schedule_once(scheduler, db):
    """A one-shot task appears in list_tasks after scheduling."""
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    task_id = await scheduler.schedule_once(
        name="Send report",
        action="Send the weekly report",
        scheduled_time=future,
    )

    tasks = await scheduler.list_tasks()
    assert len(tasks) == 1
    task = tasks[0]
    assert task["id"] == task_id
    assert task["name"] == "Send report"
    assert task["type"] == "once"
    assert task["enabled"] == 1


async def test_schedule_recurring(scheduler, db):
    """A recurring task has next_run_at set based on its cron expression."""
    before = datetime.now(timezone.utc)

    task_id = await scheduler.schedule_recurring(
        name="Daily digest",
        action="Summarize the day",
        cron_expression="0 9 * * *",
    )

    row = await db.fetch_one("SELECT * FROM scheduled_tasks WHERE id = ?", (task_id,))
    assert row is not None
    assert row["type"] == "recurring"
    assert row["schedule"] == "0 9 * * *"
    assert row["next_run_at"] is not None

    next_run = datetime.fromisoformat(row["next_run_at"])
    assert next_run > before


async def test_get_due_tasks(scheduler):
    """A task scheduled in the past is returned by get_due_tasks."""
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    task_id = await scheduler.schedule_once(
        name="Overdue reminder",
        action="Check in with team",
        scheduled_time=past,
    )

    due = await scheduler.get_due_tasks()
    assert len(due) == 1
    assert due[0]["id"] == task_id


async def test_mark_completed_once(scheduler, db):
    """Completing a one-shot task disables it."""
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    task_id = await scheduler.schedule_once(
        name="One-time ping",
        action="Ping the server",
        scheduled_time=past,
    )

    await scheduler.mark_completed(task_id)

    row = await db.fetch_one("SELECT * FROM scheduled_tasks WHERE id = ?", (task_id,))
    assert row["enabled"] == 0
    assert row["last_run_at"] is not None
