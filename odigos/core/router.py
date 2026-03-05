from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

from odigos.providers.base import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)


@dataclass
class _ModelState:
    model_id: str
    remaining_requests: int = 20
    reset_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    consecutive_failures: int = 0


class ModelRouter(LLMProvider):
    """Routes requests across a pool of free models with rate-limit awareness.

    Implements LLMProvider so it's a drop-in replacement for the raw provider.
    """

    def __init__(
        self,
        provider: LLMProvider,
        free_pool: list[str],
        rate_limit_rpm: int = 20,
    ) -> None:
        self._provider = provider
        self._rate_limit_rpm = rate_limit_rpm
        self._pool = [
            _ModelState(model_id=m, remaining_requests=rate_limit_rpm)
            for m in free_pool
        ]
        self._index = 0

    async def complete(self, messages: list[dict], **kwargs) -> LLMResponse:
        complexity = kwargs.pop("complexity", "standard")
        _ = complexity  # stored for future tier routing

        tried = 0
        last_error: Exception | None = None

        while tried < len(self._pool):
            state = self._pool[self._index]
            self._index = (self._index + 1) % len(self._pool)

            now = datetime.now(timezone.utc)
            if state.remaining_requests <= 0 and now < state.reset_at:
                tried += 1
                continue

            if now >= state.reset_at:
                state.remaining_requests = self._rate_limit_rpm
                state.consecutive_failures = 0

            try:
                result = await self._provider.complete(
                    messages, model=state.model_id, **kwargs
                )
                state.remaining_requests -= 1
                state.consecutive_failures = 0
                return result
            except RuntimeError as e:
                error_msg = str(e)
                if "429" in error_msg:
                    state.remaining_requests = 0
                    state.reset_at = now + timedelta(seconds=60)
                    logger.warning(
                        "Rate limited on %s, rotating to next model",
                        state.model_id,
                    )
                else:
                    state.consecutive_failures += 1
                    logger.warning(
                        "Model %s failed: %s", state.model_id, e
                    )
                last_error = e
                tried += 1

        raise RuntimeError(
            f"All models exhausted in free pool. Last error: {last_error}"
        )

    async def close(self) -> None:
        await self._provider.close()
