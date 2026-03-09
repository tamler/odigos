from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class UniversalMessage:
    """Platform-agnostic message format."""

    id: str
    channel: str
    sender: str
    content: str
    timestamp: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


class Channel(ABC):
    """Base class for I/O channels (Telegram, email, API, etc.)."""

    channel_name: str = ""

    @abstractmethod
    async def start(self) -> None:
        """Start listening for messages."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Stop the channel and clean up."""
        ...

    async def send_message(self, conversation_id: str, text: str) -> None:
        """Send a text message to a conversation. Override in subclasses."""
        raise NotImplementedError(f"{type(self).__name__} does not support send_message")

    async def send_approval_request(
        self, approval_id: str, tool_name: str, conversation_id: str, arguments: dict,
    ) -> None:
        """Send an approval request to a conversation. Override in subclasses."""
        raise NotImplementedError(f"{type(self).__name__} does not support send_approval_request")


class ChannelRegistry:
    """Routes messages to the correct channel based on conversation_id prefix."""

    def __init__(self) -> None:
        self._channels: dict[str, Channel] = {}

    def register(self, name: str, channel: Channel) -> None:
        channel.channel_name = name
        self._channels[name] = channel

    def get(self, name: str) -> Channel | None:
        return self._channels.get(name)

    def for_conversation(self, conversation_id: str) -> Channel | None:
        """Look up channel from conversation_id like 'telegram:123'."""
        prefix = conversation_id.split(":", 1)[0] if ":" in conversation_id else ""
        return self._channels.get(prefix)

    def all(self) -> list[Channel]:
        return list(self._channels.values())
