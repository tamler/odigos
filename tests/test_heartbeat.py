import asyncio
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock

from odigos.core.goal_store import GoalStore
from odigos.core.heartbeat import Heartbeat
from odigos.db import Database
from odigos.providers.base import LLMResponse


@pytest_asyncio.fixture
async def db(tmp_db_path):
    d = Database(tmp_db_path, migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


@pytest_asyncio.fixture
async def store(db):
    return GoalStore(db=db)


@pytest_asyncio.fixture
async def mock_agent():
    agent = MagicMock()
    agent.handle_message = AsyncMock(return_value="Done")
    return agent


@pytest_asyncio.fixture
async def mock_telegram():
    tg = MagicMock()
    tg.send_message = AsyncMock()
    return tg


@pytest_asyncio.fixture
async def mock_provider():
    provider = AsyncMock()
    provider.complete = AsyncMock(
        return_value=LLMResponse(
            content='{"idle": true}',
            model="test",
            tokens_in=10,
            tokens_out=5,
            cost_usd=0.001,
        )
    )
    return provider


@pytest_asyncio.fixture
async def heartbeat(db, mock_agent, mock_telegram, store, mock_provider):
    return Heartbeat(
        db=db,
        agent=mock_agent,
        telegram_channel=mock_telegram,
        goal_store=store,
        provider=mock_provider,
        interval=0.1,
        idle_think_interval=0,
    )


@pytest.mark.asyncio
async def test_fires_due_reminder(heartbeat, store, mock_telegram, db):
    await db.execute(
        "INSERT INTO conversations (id, channel) VALUES (?, ?)",
        ("telegram:42", "telegram"),
    )
    await store.create_reminder(
        "Call dentist", due_seconds=0, conversation_id="telegram:42",
    )
    await heartbeat._tick()
    mock_telegram.send_message.assert_called_once()
    call_args = mock_telegram.send_message.call_args
    assert 42 == call_args[0][0]


@pytest.mark.asyncio
async def test_skips_future_reminder(heartbeat, store, mock_telegram):
    await store.create_reminder("Future", due_seconds=99999)
    await heartbeat._tick()
    mock_telegram.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_marks_reminder_fired(heartbeat, store, db):
    rid = await store.create_reminder("Fire me", due_seconds=0)
    await heartbeat._tick()
    row = await db.fetch_one("SELECT * FROM reminders WHERE id = ?", (rid,))
    assert row["status"] == "fired"


@pytest.mark.asyncio
async def test_works_on_pending_todo(heartbeat, store, mock_agent, db):
    tid = await store.create_todo("Say hello")
    await heartbeat._tick()
    mock_agent.handle_message.assert_called_once()
    row = await db.fetch_one("SELECT * FROM todos WHERE id = ?", (tid,))
    assert row["status"] == "completed"


@pytest.mark.asyncio
async def test_skips_future_todo(heartbeat, store, mock_agent):
    await store.create_todo("Future task", delay_seconds=99999)
    await heartbeat._tick()
    mock_agent.handle_message.assert_not_called()


@pytest.mark.asyncio
async def test_todo_failure_marks_failed(heartbeat, store, mock_agent, db):
    mock_agent.handle_message = AsyncMock(side_effect=RuntimeError("boom"))
    tid = await store.create_todo("Fail me")
    await heartbeat._tick()
    row = await db.fetch_one("SELECT * FROM todos WHERE id = ?", (tid,))
    assert row["status"] == "failed"


@pytest.mark.asyncio
async def test_sends_todo_result_to_conversation(heartbeat, store, mock_telegram, db):
    await db.execute(
        "INSERT INTO conversations (id, channel) VALUES (?, ?)",
        ("telegram:42", "telegram"),
    )
    await store.create_todo("Do something", conversation_id="telegram:42")
    await heartbeat._tick()
    mock_telegram.send_message.assert_called_once()
    call_args = mock_telegram.send_message.call_args
    assert 42 == call_args[0][0]


@pytest.mark.asyncio
async def test_paused_heartbeat_skips(heartbeat, store, mock_agent, mock_telegram):
    heartbeat.paused = True
    await store.create_todo("Should not run")
    await store.create_reminder("Should not fire", due_seconds=0)
    await heartbeat._tick()
    mock_agent.handle_message.assert_not_called()
    mock_telegram.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_start_and_stop(heartbeat):
    await heartbeat.start()
    assert heartbeat._task is not None
    assert not heartbeat._task.done()
    await heartbeat.stop()
    await asyncio.sleep(0.05)
    assert heartbeat._task.cancelled() or heartbeat._task.done()


@pytest.mark.asyncio
async def test_max_todos_per_tick(heartbeat, store, mock_agent):
    heartbeat._max_todos_per_tick = 2
    for i in range(5):
        await store.create_todo(f"Task {i}")
    await heartbeat._tick()
    assert mock_agent.handle_message.call_count == 2


@pytest.mark.asyncio
async def test_recurring_reminder_reinserts(heartbeat, store, db):
    rid = await store.create_reminder("Daily check", due_seconds=0, recurrence="daily")
    await heartbeat._tick()
    row = await db.fetch_one("SELECT * FROM reminders WHERE id = ?", (rid,))
    assert row["status"] == "fired"
    pending = await store.list_reminders(status="pending")
    assert len(pending) == 1
    assert pending[0]["id"] != rid
    assert pending[0]["description"] == "Daily check"
    assert pending[0]["recurrence"] == "daily"


@pytest.mark.asyncio
async def test_recurring_every_ns_pattern(heartbeat, store, db):
    rid = await store.create_reminder("Custom", due_seconds=0, recurrence="every 7200s")
    await heartbeat._tick()
    pending = await store.list_reminders(status="pending")
    assert len(pending) == 1
    assert pending[0]["recurrence"] == "every 7200s"


@pytest.mark.asyncio
async def test_idle_think_creates_todo(heartbeat, store, mock_provider, db):
    """Idle-think creates a todo when LLM responds with a todo."""
    await store.create_goal("Learn Spanish")
    mock_provider.complete = AsyncMock(
        return_value=LLMResponse(
            content='{"todo": "Find Spanish learning resources"}',
            model="test", tokens_in=10, tokens_out=10, cost_usd=0.001,
        )
    )
    await heartbeat._tick()
    todos = await store.list_todos()
    assert len(todos) == 1
    assert todos[0]["description"] == "Find Spanish learning resources"
    assert todos[0]["created_by"] == "agent"


@pytest.mark.asyncio
async def test_idle_think_updates_goal_progress(heartbeat, store, mock_provider, db):
    """Idle-think updates a goal's progress_note."""
    gid = await store.create_goal("Read more books")
    short_id = gid[:8]
    mock_provider.complete = AsyncMock(
        return_value=LLMResponse(
            content=f'{{"note": "{short_id}", "progress": "Started reading list"}}',
            model="test", tokens_in=10, tokens_out=10, cost_usd=0.001,
        )
    )
    await heartbeat._tick()
    row = await db.fetch_one("SELECT * FROM goals WHERE id = ?", (gid,))
    assert row["progress_note"] == "Started reading list"
    assert row["reviewed_at"] is not None


@pytest.mark.asyncio
async def test_idle_think_skips_when_todos_ran(heartbeat, store, mock_provider):
    """Idle-think does NOT fire when todos ran in the same tick."""
    await store.create_goal("Some goal")
    await store.create_todo("Do something")
    await heartbeat._tick()
    mock_provider.complete.assert_not_called()


@pytest.mark.asyncio
async def test_idle_think_noop_on_idle_response(heartbeat, store, mock_provider, db):
    """Idle-think does nothing when LLM says idle."""
    await store.create_goal("Some goal")
    # mock_provider already returns {"idle": true} by default
    await heartbeat._tick()
    todos = await store.list_todos()
    assert len(todos) == 0


@pytest.mark.asyncio
async def test_idle_think_handles_markdown_wrapped_json(heartbeat, store, mock_provider, db):
    """Idle-think extracts JSON from markdown code blocks."""
    await store.create_goal("Learn Spanish")
    mock_provider.complete = AsyncMock(
        return_value=LLMResponse(
            content='```json\n{"todo": "Practice vocabulary"}\n```',
            model="test", tokens_in=10, tokens_out=10, cost_usd=0.001,
        )
    )
    await heartbeat._tick()
    todos = await store.list_todos()
    assert len(todos) == 1
    assert todos[0]["description"] == "Practice vocabulary"
