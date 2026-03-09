from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import defaultdict
from collections.abc import Callable

from odigos.db import Database

logger = logging.getLogger(__name__)

HOOK_TIMEOUT = 5.0


class Tracer:
    """Structured event tracing with DB persistence."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self._subscribers: dict[str, list[Callable]] = defaultdict(list)

    def subscribe(self, event_type: str, callback: Callable) -> None:
        """Register a callback for a specific event type."""
        self._subscribers[event_type].append(callback)

    def clear_subscribers(self) -> None:
        """Remove all registered subscribers."""
        self._subscribers.clear()

    async def emit(
        self,
        event_type: str,
        conversation_id: str | None,
        data: dict,
    ) -> str:
        """Emit a trace event. Returns the trace ID."""
        trace_id = str(uuid.uuid4())
        try:
            await self.db.execute(
                "INSERT INTO traces (id, conversation_id, event_type, data_json) "
                "VALUES (?, ?, ?, ?)",
                (trace_id, conversation_id, event_type, json.dumps(data)),
            )
        except Exception:
            logger.debug("Failed to emit trace", exc_info=True)

        for callback in self._subscribers.get(event_type, []):
            try:
                await asyncio.wait_for(
                    callback(event_type, conversation_id, data),
                    timeout=HOOK_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Subscriber %s timed out for event %s",
                    callback,
                    event_type,
                )
            except Exception:
                logger.warning(
                    "Subscriber %s failed for event %s",
                    callback,
                    event_type,
                    exc_info=True,
                )

        return trace_id
