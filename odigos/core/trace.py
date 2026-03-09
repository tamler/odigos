from __future__ import annotations

import json
import logging
import uuid

from odigos.db import Database

logger = logging.getLogger(__name__)


class Tracer:
    """Structured event tracing with DB persistence."""

    def __init__(self, db: Database) -> None:
        self.db = db

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
        return trace_id
