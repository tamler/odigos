from datetime import datetime, timezone

from odigos.channels.base import UniversalMessage


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
