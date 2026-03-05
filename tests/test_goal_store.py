import pytest
import pytest_asyncio
from odigos.core.goal_store import GoalStore
from odigos.db import Database


@pytest_asyncio.fixture
async def db(tmp_db_path):
    d = Database(tmp_db_path, migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


@pytest_asyncio.fixture
async def store(db):
    return GoalStore(db=db)


class TestGoalStoreSchema:
    async def test_goals_table_exists(self, db):
        row = await db.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='goals'"
        )
        assert row is not None

    async def test_todos_table_exists(self, db):
        row = await db.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='todos'"
        )
        assert row is not None

    async def test_reminders_table_exists(self, db):
        row = await db.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='reminders'"
        )
        assert row is not None

    async def test_tasks_table_dropped(self, db):
        row = await db.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'"
        )
        assert row is None


class TestGoalCRUD:
    async def test_create_goal(self, store, db):
        goal_id = await store.create_goal("Learn Spanish")
        row = await db.fetch_one("SELECT * FROM goals WHERE id = ?", (goal_id,))
        assert row is not None
        assert row["description"] == "Learn Spanish"
        assert row["status"] == "active"
        assert row["created_by"] == "user"

    async def test_create_goal_by_agent(self, store, db):
        goal_id = await store.create_goal("Review tool usage", created_by="agent")
        row = await db.fetch_one("SELECT * FROM goals WHERE id = ?", (goal_id,))
        assert row["created_by"] == "agent"

    async def test_list_goals(self, store):
        await store.create_goal("Goal A")
        await store.create_goal("Goal B")
        goals = await store.list_goals()
        assert len(goals) == 2

    async def test_list_goals_filters_by_status(self, store):
        gid = await store.create_goal("Done goal")
        await store.update_goal(gid, status="completed")
        active = await store.list_goals(status="active")
        assert len(active) == 0
        completed = await store.list_goals(status="completed")
        assert len(completed) == 1

    async def test_update_goal(self, store, db):
        gid = await store.create_goal("Original")
        await store.update_goal(gid, progress_note="Made some progress")
        row = await db.fetch_one("SELECT * FROM goals WHERE id = ?", (gid,))
        assert row["progress_note"] == "Made some progress"


class TestTodoCRUD:
    async def test_create_todo(self, store, db):
        todo_id = await store.create_todo("Buy groceries")
        row = await db.fetch_one("SELECT * FROM todos WHERE id = ?", (todo_id,))
        assert row is not None
        assert row["description"] == "Buy groceries"
        assert row["status"] == "pending"
        assert row["scheduled_at"] is None

    async def test_create_delayed_todo(self, store, db):
        todo_id = await store.create_todo("Do laundry", delay_seconds=3600)
        row = await db.fetch_one("SELECT * FROM todos WHERE id = ?", (todo_id,))
        assert row["scheduled_at"] is not None

    async def test_create_todo_with_goal(self, store, db):
        goal_id = await store.create_goal("Stay healthy")
        todo_id = await store.create_todo("Go for a run", goal_id=goal_id)
        row = await db.fetch_one("SELECT * FROM todos WHERE id = ?", (todo_id,))
        assert row["goal_id"] == goal_id

    async def test_list_todos(self, store):
        await store.create_todo("A")
        await store.create_todo("B")
        todos = await store.list_todos()
        assert len(todos) == 2

    async def test_complete_todo(self, store, db):
        tid = await store.create_todo("Finish report")
        await store.complete_todo(tid, result="Done")
        row = await db.fetch_one("SELECT * FROM todos WHERE id = ?", (tid,))
        assert row["status"] == "completed"
        assert row["result"] == "Done"

    async def test_fail_todo(self, store, db):
        tid = await store.create_todo("Broken task")
        await store.fail_todo(tid, error="Something went wrong")
        row = await db.fetch_one("SELECT * FROM todos WHERE id = ?", (tid,))
        assert row["status"] == "failed"
        assert row["error"] == "Something went wrong"


class TestReminderCRUD:
    async def test_create_reminder(self, store, db):
        rid = await store.create_reminder("Call dentist", due_seconds=7200)
        row = await db.fetch_one("SELECT * FROM reminders WHERE id = ?", (rid,))
        assert row is not None
        assert row["description"] == "Call dentist"
        assert row["status"] == "pending"
        assert row["due_at"] is not None

    async def test_create_recurring_reminder(self, store, db):
        rid = await store.create_reminder("Check email", due_seconds=0, recurrence="daily")
        row = await db.fetch_one("SELECT * FROM reminders WHERE id = ?", (rid,))
        assert row["recurrence"] == "daily"

    async def test_list_reminders(self, store):
        await store.create_reminder("A", due_seconds=0)
        await store.create_reminder("B", due_seconds=3600)
        reminders = await store.list_reminders()
        assert len(reminders) == 2

    async def test_cancel_reminder(self, store, db):
        rid = await store.create_reminder("Cancel me", due_seconds=0)
        result = await store.cancel_reminder(rid)
        assert result is True
        row = await db.fetch_one("SELECT * FROM reminders WHERE id = ?", (rid,))
        assert row["status"] == "cancelled"


class TestCrossTableCancel:
    async def test_cancel_goal(self, store, db):
        gid = await store.create_goal("Cancel me")
        result = await store.cancel(gid)
        assert result is True
        row = await db.fetch_one("SELECT * FROM goals WHERE id = ?", (gid,))
        assert row["status"] == "archived"

    async def test_cancel_todo(self, store, db):
        tid = await store.create_todo("Cancel me")
        result = await store.cancel(tid)
        assert result is True
        row = await db.fetch_one("SELECT * FROM todos WHERE id = ?", (tid,))
        assert row["status"] == "failed"

    async def test_cancel_reminder(self, store, db):
        rid = await store.create_reminder("Cancel me", due_seconds=0)
        result = await store.cancel(rid)
        assert result is True
        row = await db.fetch_one("SELECT * FROM reminders WHERE id = ?", (rid,))
        assert row["status"] == "cancelled"

    async def test_cancel_nonexistent_returns_false(self, store):
        result = await store.cancel("nonexistent-id")
        assert result is False
