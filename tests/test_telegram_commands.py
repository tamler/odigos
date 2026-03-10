# tests/test_telegram_commands.py
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_send_message():
    from odigos.channels.telegram import TelegramChannel

    agent = MagicMock()
    channel = TelegramChannel(token="fake", agent=agent)

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()
    mock_app = MagicMock()
    mock_app.bot = mock_bot
    channel._app = mock_app

    await channel.send_message(12345, "Hello!")
    mock_bot.send_message.assert_called_once_with(chat_id=12345, text="Hello!")


@pytest.mark.asyncio
async def test_goals_command():
    from odigos.channels.telegram import TelegramChannel

    agent = MagicMock()
    goal_store = MagicMock()
    goal_store.list_goals = AsyncMock(return_value=[
        {"id": "abc12345-full-uuid", "description": "Learn Python", "progress_note": "started chapter 1"},
    ])

    channel = TelegramChannel(token="fake", agent=agent, goal_store=goal_store)

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.reply_text = AsyncMock()
    context = MagicMock()

    await channel._handle_goals_command(update, context)
    call_text = update.effective_message.reply_text.call_args[0][0]
    assert "Learn Python" in call_text
    assert "started chapter 1" in call_text


@pytest.mark.asyncio
async def test_goals_command_empty():
    from odigos.channels.telegram import TelegramChannel

    agent = MagicMock()
    goal_store = MagicMock()
    goal_store.list_goals = AsyncMock(return_value=[])

    channel = TelegramChannel(token="fake", agent=agent, goal_store=goal_store)

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.reply_text = AsyncMock()
    context = MagicMock()

    await channel._handle_goals_command(update, context)
    call_text = update.effective_message.reply_text.call_args[0][0]
    assert "No active goals" in call_text


@pytest.mark.asyncio
async def test_todos_command():
    from odigos.channels.telegram import TelegramChannel

    agent = MagicMock()
    goal_store = MagicMock()
    goal_store.list_todos = AsyncMock(return_value=[
        {"id": "abc12345-full-uuid", "description": "Check email", "scheduled_at": "2026-03-05T10:00:00"},
    ])

    channel = TelegramChannel(token="fake", agent=agent, goal_store=goal_store)

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.reply_text = AsyncMock()
    context = MagicMock()

    await channel._handle_todos_command(update, context)
    call_text = update.effective_message.reply_text.call_args[0][0]
    assert "Check email" in call_text


@pytest.mark.asyncio
async def test_todos_command_empty():
    from odigos.channels.telegram import TelegramChannel

    agent = MagicMock()
    goal_store = MagicMock()
    goal_store.list_todos = AsyncMock(return_value=[])

    channel = TelegramChannel(token="fake", agent=agent, goal_store=goal_store)

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.reply_text = AsyncMock()
    context = MagicMock()

    await channel._handle_todos_command(update, context)
    call_text = update.effective_message.reply_text.call_args[0][0]
    assert "No pending todos" in call_text


@pytest.mark.asyncio
async def test_reminders_command():
    from odigos.channels.telegram import TelegramChannel

    agent = MagicMock()
    goal_store = MagicMock()
    goal_store.list_reminders = AsyncMock(return_value=[
        {"id": "rem12345-full-uuid", "description": "Stand up", "due_at": "2026-03-05T14:00:00", "recurrence": "daily"},
    ])

    channel = TelegramChannel(token="fake", agent=agent, goal_store=goal_store)

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.reply_text = AsyncMock()
    context = MagicMock()

    await channel._handle_reminders_command(update, context)
    call_text = update.effective_message.reply_text.call_args[0][0]
    assert "Stand up" in call_text
    assert "recurring: daily" in call_text


@pytest.mark.asyncio
async def test_reminders_command_empty():
    from odigos.channels.telegram import TelegramChannel

    agent = MagicMock()
    goal_store = MagicMock()
    goal_store.list_reminders = AsyncMock(return_value=[])

    channel = TelegramChannel(token="fake", agent=agent, goal_store=goal_store)

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.reply_text = AsyncMock()
    context = MagicMock()

    await channel._handle_reminders_command(update, context)
    call_text = update.effective_message.reply_text.call_args[0][0]
    assert "No pending reminders" in call_text


@pytest.mark.asyncio
async def test_cancel_command():
    from odigos.channels.telegram import TelegramChannel

    agent = MagicMock()
    goal_store = MagicMock()
    goal_store.cancel = AsyncMock(return_value=True)
    goal_store.list_goals = AsyncMock(return_value=[])
    goal_store.list_todos = AsyncMock(return_value=[
        {"id": "abc-123-full-uuid", "description": "test todo"},
    ])
    goal_store.list_reminders = AsyncMock(return_value=[])

    channel = TelegramChannel(token="fake", agent=agent, goal_store=goal_store)

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.text = "/cancel abc-123"
    update.effective_message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = ["abc-123"]

    await channel._handle_cancel_command(update, context)
    goal_store.cancel.assert_called_once_with("abc-123-full-uuid")
    call_text = update.effective_message.reply_text.call_args[0][0]
    assert "cancelled" in call_text.lower()


@pytest.mark.asyncio
async def test_cancel_command_no_args():
    from odigos.channels.telegram import TelegramChannel

    agent = MagicMock()
    goal_store = MagicMock()

    channel = TelegramChannel(token="fake", agent=agent, goal_store=goal_store)

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = []

    await channel._handle_cancel_command(update, context)
    call_text = update.effective_message.reply_text.call_args[0][0]
    assert "Usage" in call_text


@pytest.mark.asyncio
async def test_stop_command_pauses_heartbeat():
    from odigos.channels.telegram import TelegramChannel

    agent = MagicMock()
    heartbeat = MagicMock()
    heartbeat.paused = False
    agent.heartbeat = heartbeat

    channel = TelegramChannel(token="fake", agent=agent)

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.reply_text = AsyncMock()
    context = MagicMock()

    await channel._handle_stop_command(update, context)
    assert heartbeat.paused is True


@pytest.mark.asyncio
async def test_start_command_resumes_heartbeat():
    from odigos.channels.telegram import TelegramChannel

    agent = MagicMock()
    heartbeat = MagicMock()
    heartbeat.paused = True
    agent.heartbeat = heartbeat

    channel = TelegramChannel(token="fake", agent=agent)

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.reply_text = AsyncMock()
    context = MagicMock()

    await channel._handle_start_command(update, context)
    assert heartbeat.paused is False


@pytest.mark.asyncio
async def test_status_command():
    from odigos.channels.telegram import TelegramChannel

    agent = MagicMock()
    budget_tracker = AsyncMock()
    budget_tracker.check_budget = AsyncMock(return_value=AsyncMock(
        within_budget=True,
        warning=False,
        daily_spend=0.05,
        monthly_spend=1.20,
        daily_limit=3.00,
        monthly_limit=50.00,
    ))
    goal_store = MagicMock()
    goal_store.list_goals = AsyncMock(return_value=[
        {"id": "g1", "description": "goal1"},
    ])
    goal_store.list_todos = AsyncMock(return_value=[
        {"id": "t1", "description": "todo1"},
        {"id": "t2", "description": "todo2"},
    ])
    goal_store.list_reminders = AsyncMock(return_value=[
        {"id": "r1", "description": "reminder1"},
    ])
    heartbeat = MagicMock()
    heartbeat.paused = False

    agent.heartbeat = heartbeat

    channel = TelegramChannel(
        token="fake", agent=agent,
        budget_tracker=budget_tracker, goal_store=goal_store,
    )

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.reply_text = AsyncMock()
    context = MagicMock()

    await channel._handle_status_command(update, context)
    call_text = update.effective_message.reply_text.call_args[0][0]
    assert "Budget:" in call_text
    assert "$0.0500" in call_text
    assert "Goals: 1 active" in call_text
    assert "Todos: 2 pending" in call_text
    assert "Reminders: 1 pending" in call_text
    assert "Heartbeat: running" in call_text
