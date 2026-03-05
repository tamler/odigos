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

    await channel.send_message(chat_id=12345, text="Hello!")
    mock_bot.send_message.assert_called_once_with(chat_id=12345, text="Hello!")


@pytest.mark.asyncio
async def test_tasks_command():
    from odigos.channels.telegram import TelegramChannel

    agent = MagicMock()
    scheduler = MagicMock()
    scheduler.list_pending = AsyncMock(return_value=[
        {"id": "abc", "description": "Check email", "scheduled_at": "2026-03-05T10:00:00", "priority": 1},
    ])

    channel = TelegramChannel(token="fake", agent=agent, scheduler=scheduler)

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.reply_text = AsyncMock()
    context = MagicMock()

    await channel._handle_tasks_command(update, context)
    call_text = update.effective_message.reply_text.call_args[0][0]
    assert "Check email" in call_text


@pytest.mark.asyncio
async def test_cancel_command():
    from odigos.channels.telegram import TelegramChannel

    agent = MagicMock()
    scheduler = MagicMock()
    scheduler.cancel = AsyncMock(return_value=True)
    scheduler.list_pending = AsyncMock(return_value=[
        {"id": "abc-123-full-uuid", "description": "test task"},
    ])

    channel = TelegramChannel(token="fake", agent=agent, scheduler=scheduler)

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.text = "/cancel abc-123"
    update.effective_message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = ["abc-123"]

    await channel._handle_cancel_command(update, context)
    scheduler.cancel.assert_called_once_with("abc-123-full-uuid")
    call_text = update.effective_message.reply_text.call_args[0][0]
    assert "cancelled" in call_text.lower()


@pytest.mark.asyncio
async def test_stop_command_pauses_heartbeat():
    from odigos.channels.telegram import TelegramChannel

    agent = MagicMock()
    heartbeat = MagicMock()
    heartbeat.paused = False

    channel = TelegramChannel(token="fake", agent=agent, heartbeat=heartbeat)

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

    channel = TelegramChannel(token="fake", agent=agent, heartbeat=heartbeat)

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
    scheduler = MagicMock()
    scheduler.list_pending = AsyncMock(return_value=[
        {"id": "t1", "description": "task1"},
        {"id": "t2", "description": "task2"},
    ])
    heartbeat = MagicMock()
    heartbeat.paused = False

    channel = TelegramChannel(
        token="fake", agent=agent,
        budget_tracker=budget_tracker, scheduler=scheduler, heartbeat=heartbeat,
    )

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.reply_text = AsyncMock()
    context = MagicMock()

    await channel._handle_status_command(update, context)
    call_text = update.effective_message.reply_text.call_args[0][0]
    assert "Budget:" in call_text
    assert "$0.0500" in call_text
    assert "Pending tasks: 2" in call_text
    assert "Heartbeat: running" in call_text
