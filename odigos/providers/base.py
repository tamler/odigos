from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class LLMResponse:
    content: str
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    generation_id: str | None = None
    tool_calls: list[ToolCall] | None = None


class LLMProvider(ABC):
    @abstractmethod
    async def complete(self, messages: list[dict], **kwargs) -> LLMResponse:
        """Send messages to the LLM and get a response."""
        ...

    async def stream_complete(self, messages: list[dict], **kwargs):
        """Stream response tokens. Yields (chunk_text, None) for content chunks,
        then (None, LLMResponse) for the final complete response.

        Default implementation falls back to non-streaming complete().
        Override in subclasses that support streaming.
        """
        response = await self.complete(messages, **kwargs)
        yield response.content, response

    async def close(self) -> None:
        """Clean up resources."""
        pass
