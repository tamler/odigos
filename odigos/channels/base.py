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

    @abstractmethod
    async def start(self) -> None:
        """Start listening for messages."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Stop the channel and clean up."""
        ...
