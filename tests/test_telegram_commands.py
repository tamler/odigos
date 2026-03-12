# tests/test_telegram_commands.py
import pytest
from unittest.mock import AsyncMock, MagicMock

from odigos.core.agent_service import AgentService


def _make_service(**overrides):
    """Create a mock AgentService with sensible defaults."""
    service = MagicMock(spec=AgentService)
    service.handle_message = AsyncMock(return_value="ok")
    service.list_goals = AsyncMock(return_value=[])
    service.list_todos = AsyncMock(return_value=[])
    service.list_reminders = AsyncMock(return_value=[])
    service.cancel_item = AsyncMock(return_value=True)
    service.check_budget = AsyncMock(return_value=MagicMock(
        within_budget=True, warning=False,
        daily_spend=0.0, monthly_spend=0.0,
        daily_limit=1.0, monthly_limit=20.0,
    ))
    service.heartbeat_paused = False
    service.pause_heartbeat = MagicMock()
    service.resume_heartbeat = MagicMock()
    service.resolve_approval = MagicMock(return_value=False)
    for key, val in overrides.items():
        setattr(service, key, val)
    return service


def _make_channel(service):
    from odigos.channels.telegram import TelegramChannel
    return TelegramChannel(token="fake", service=service)


@pytest.mark.asyncio
async def test_send_message():
    from odigos.channels.telegram import TelegramChannel

    service = _make_service()
    channel = TelegramChannel(token="fake", service=service)

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()
    mock_app = MagicMock()
    mock_app.bot = mock_bot
    channel._app = mock_app

    await channel.send_message(12345, "Hello!")
    mock_bot.send_message.assert_called_once_with(chat_id=12345, text="Hello!")


@pytest.mark.asyncio
async def test_goals_command():
    service = _make_service(
        list_goals=AsyncMock(return_value=[
            {"id": "abc12345-full-uuid", "description": "Learn Python", "progress_note": "started chapter 1"},
        ]),
    )
    channel = _make_channel(service)

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
    service = _make_service()
    channel = _make_channel(service)

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.reply_text = AsyncMock()
    context = MagicMock()

    await channel._handle_goals_command(update, context)
    call_text = update.effective_message.reply_text.call_args[0][0]
    assert "No active goals" in call_text


@pytest.mark.asyncio
async def test_todos_command():
    service = _make_service(
        list_todos=AsyncMock(return_value=[
            {"id": "abc12345-full-uuid", "description": "Check email", "scheduled_at": "2026-03-05T10:00:00"},
        ]),
    )
    channel = _make_channel(service)

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.reply_text = AsyncMock()
    context = MagicMock()

    await channel._handle_todos_command(update, context)
    call_text = update.effective_message.reply_text.call_args[0][0]
    assert "Check email" in call_text


@pytest.mark.asyncio
async def test_todos_command_empty():
    service = _make_service()
    channel = _make_channel(service)

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.reply_text = AsyncMock()
    context = MagicMock()

    await channel._handle_todos_command(update, context)
    call_text = update.effective_message.reply_text.call_args[0][0]
    assert "No pending todos" in call_text


@pytest.mark.asyncio
async def test_reminders_command():
    service = _make_service(
        list_reminders=AsyncMock(return_value=[
            {"id": "rem12345-full-uuid", "description": "Stand up", "due_at": "2026-03-05T14:00:00", "recurrence": "daily"},
        ]),
    )
    channel = _make_channel(service)

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
    service = _make_service()
    channel = _make_channel(service)

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.reply_text = AsyncMock()
    context = MagicMock()

    await channel._handle_reminders_command(update, context)
    call_text = update.effective_message.reply_text.call_args[0][0]
    assert "No pending reminders" in call_text


@pytest.mark.asyncio
async def test_cancel_command():
    service = _make_service(
        list_goals=AsyncMock(return_value=[]),
        list_todos=AsyncMock(return_value=[
            {"id": "abc-123-full-uuid", "description": "test todo"},
        ]),
        list_reminders=AsyncMock(return_value=[]),
    )
    channel = _make_channel(service)

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.text = "/cancel abc-123"
    update.effective_message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = ["abc-123"]

    await channel._handle_cancel_command(update, context)
    service.cancel_item.assert_called_once_with("abc-123-full-uuid")
    call_text = update.effective_message.reply_text.call_args[0][0]
    assert "cancelled" in call_text.lower()


@pytest.mark.asyncio
async def test_cancel_command_no_args():
    service = _make_service()
    channel = _make_channel(service)

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
    service = _make_service(heartbeat_paused=False)
    channel = _make_channel(service)

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.reply_text = AsyncMock()
    context = MagicMock()

    await channel._handle_stop_command(update, context)
    service.pause_heartbeat.assert_called_once()


@pytest.mark.asyncio
async def test_start_command_resumes_heartbeat():
    service = _make_service(heartbeat_paused=True)
    channel = _make_channel(service)

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.reply_text = AsyncMock()
    context = MagicMock()

    await channel._handle_start_command(update, context)
    service.resume_heartbeat.assert_called_once()


@pytest.mark.asyncio
async def test_status_command():
    service = _make_service(
        check_budget=AsyncMock(return_value=MagicMock(
            within_budget=True,
            warning=False,
            daily_spend=0.05,
            monthly_spend=1.20,
            daily_limit=3.00,
            monthly_limit=50.00,
        )),
        list_goals=AsyncMock(return_value=[
            {"id": "g1", "description": "goal1"},
        ]),
        list_todos=AsyncMock(return_value=[
            {"id": "t1", "description": "todo1"},
            {"id": "t2", "description": "todo2"},
        ]),
        list_reminders=AsyncMock(return_value=[
            {"id": "r1", "description": "reminder1"},
        ]),
        heartbeat_paused=False,
    )
    channel = _make_channel(service)

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
