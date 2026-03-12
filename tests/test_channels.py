from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from odigos.channels.base import UniversalMessage
from odigos.channels.telegram import TelegramChannel
from odigos.core.agent_service import AgentService


def test_universal_message_creation():
    """UniversalMessage holds all required fields."""
    msg = UniversalMessage(
        id="msg-1",
        channel="telegram",
        sender="user-123",
        content="Hello agent",
        timestamp=datetime(2026, 3, 4, tzinfo=timezone.utc),
        metadata={"chat_id": 12345},
    )
    assert msg.id == "msg-1"
    assert msg.channel == "telegram"
    assert msg.content == "Hello agent"
    assert msg.metadata["chat_id"] == 12345


@pytest.fixture
def mock_service() -> MagicMock:
    service = MagicMock(spec=AgentService)
    service.handle_message = AsyncMock(return_value="Agent response")
    return service


async def test_telegram_converts_update_to_universal_message(mock_service: MagicMock):
    """Telegram handler converts telegram Update to UniversalMessage."""
    channel = TelegramChannel(
        token="test-token",
        service=mock_service,
        mode="polling",
    )

    # Create a mock Telegram Update
    update = MagicMock()
    update.effective_message.text = "Hello"
    update.effective_message.message_id = 42
    update.effective_chat.id = 12345
    update.effective_user.id = 67890
    update.effective_user.username = "testuser"

    context = MagicMock()
    context.bot.send_chat_action = AsyncMock()
    update.effective_message.reply_text = AsyncMock()

    await channel._handle_text(update, context)

    # Verify the service was called with a UniversalMessage
    mock_service.handle_message.assert_called_once()
    msg = mock_service.handle_message.call_args[0][0]
    assert msg.channel == "telegram"
    assert msg.content == "Hello"
    assert msg.metadata["chat_id"] == 12345

    # Verify reply was sent
    update.effective_message.reply_text.assert_called_once_with("Agent response")
