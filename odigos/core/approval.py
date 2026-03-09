from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import TYPE_CHECKING

from odigos.db import Database

if TYPE_CHECKING:
    from odigos.channels.base import ChannelRegistry

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 300  # 5 minutes


class ApprovalGate:
    """Intercepts tool calls that require user approval before execution.

    If approval_gate is None in the executor, no approval logic runs.
    Tools not in the gated set execute immediately with no overhead.
    """

    def __init__(
        self,
        db: Database,
        tools_requiring_approval: list[str],
        channel_registry: ChannelRegistry | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.db = db
        self._gated_tools: set[str] = set(tools_requiring_approval)
        self._pending: dict[str, asyncio.Future] = {}
        self.channel_registry = channel_registry
        self._timeout = timeout

    def requires_approval(self, tool_name: str) -> bool:
        return tool_name in self._gated_tools

    async def request(
        self,
        tool_name: str,
        arguments: dict,
        conversation_id: str | None = None,
    ) -> str:
        """Request approval. Returns 'approved', 'denied', or 'timeout'."""
        approval_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        future: asyncio.Future[str] = loop.create_future()
        self._pending[approval_id] = future

        # Log to DB
        await self.db.execute(
            "INSERT INTO approvals (id, conversation_id, tool_name, arguments_json, decision) "
            "VALUES (?, ?, ?, ?, 'pending')",
            (approval_id, conversation_id, tool_name, json.dumps(arguments)),
        )

        # Route notification to the originating channel
        if self.channel_registry and conversation_id:
            channel = self.channel_registry.for_conversation(conversation_id)
            if channel:
                try:
                    await channel.send_approval_request(
                        approval_id, tool_name, conversation_id, arguments,
                    )
                except Exception:
                    logger.exception("Failed to send approval notification for %s", approval_id)

        # Wait for resolution or timeout
        try:
            decision = await asyncio.wait_for(future, timeout=self._timeout)
        except asyncio.TimeoutError:
            decision = "timeout"
            self._pending.pop(approval_id, None)

        # Update DB
        await self.db.execute(
            "UPDATE approvals SET decision = ?, resolved_at = datetime('now') WHERE id = ?",
            (decision, approval_id),
        )

        logger.info("Approval %s for %s: %s", approval_id[:8], tool_name, decision)
        return decision

    def resolve(self, approval_id: str, decision: str) -> bool:
        """Resolve a pending approval. Returns True if found and resolved."""
        future = self._pending.pop(approval_id, None)
        if future is None or future.done():
            return False
        future.set_result(decision)
        return True

    @property
    def gated_tools(self) -> set[str]:
        return self._gated_tools

    def add_tool(self, tool_name: str) -> None:
        self._gated_tools.add(tool_name)

    def remove_tool(self, tool_name: str) -> None:
        self._gated_tools.discard(tool_name)
