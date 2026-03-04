from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LLMResponse:
    content: str
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: float


class LLMProvider(ABC):
    @abstractmethod
    async def complete(self, messages: list[dict], **kwargs) -> LLMResponse:
        """Send messages to the LLM and get a response."""
        ...

    async def close(self) -> None:
        """Clean up resources."""
        pass
