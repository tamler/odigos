from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from odigos.db import Database
from odigos.providers.base import LLMProvider
from odigos.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from odigos.core.trace import Tracer
    from odigos.memory.manager import MemoryManager

logger = logging.getLogger(__name__)

MAX_CONCURRENT_PER_CONVERSATION = 3
DEFAULT_TIMEOUT = 600


class SubagentManager:
    """Manages subagent lifecycle: spawn, execute, store results."""

    def __init__(
        self,
        db: Database,
        provider: LLMProvider,
        tool_registry: ToolRegistry,
        tracer: Tracer | None = None,
        memory_manager: MemoryManager | None = None,
    ) -> None:
        self.db = db
        self.provider = provider
        self.tool_registry = tool_registry
        self.tracer = tracer
        self.memory_manager = memory_manager
        self._tasks: dict[str, asyncio.Task] = {}

    async def spawn(
        self,
        instruction: str,
        parent_conversation_id: str,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> str:
        """Spawn a new subagent task. Returns the subagent ID."""
        running = await self.db.fetch_one(
            "SELECT COUNT(*) AS cnt FROM subagent_tasks "
            "WHERE parent_conversation_id = ? AND status = 'running'",
            (parent_conversation_id,),
        )
        if running and running["cnt"] >= MAX_CONCURRENT_PER_CONVERSATION:
            raise ValueError(
                f"Max concurrent subagents ({MAX_CONCURRENT_PER_CONVERSATION}) "
                f"reached for conversation {parent_conversation_id}"
            )

        subagent_id = str(uuid.uuid4())
        await self.db.execute(
            "INSERT INTO subagent_tasks (id, parent_conversation_id, instruction, status) "
            "VALUES (?, ?, ?, 'running')",
            (subagent_id, parent_conversation_id, instruction),
        )

        task = asyncio.create_task(
            self._run_subagent(subagent_id, instruction, parent_conversation_id, timeout)
        )
        self._tasks[subagent_id] = task
        return subagent_id

    async def _run_subagent(
        self,
        subagent_id: str,
        instruction: str,
        parent_conversation_id: str,
        timeout: int,
    ) -> None:
        """Execute a subagent task in the background."""
        try:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a focused subagent. Complete the given task concisely. "
                        "Do not ask follow-up questions."
                    ),
                },
            ]

            if self.memory_manager:
                try:
                    memory_context = await self.memory_manager.recall(instruction)
                    if memory_context:
                        messages.append(
                            {"role": "system", "content": f"Relevant context:\n{memory_context}"}
                        )
                except Exception:
                    logger.debug("Memory recall failed for subagent %s", subagent_id, exc_info=True)

            messages.append({"role": "user", "content": instruction})

            restricted_registry = self._build_restricted_registry()
            async with asyncio.timeout(timeout):
                response = await self.provider.complete(
                    messages, tools=restricted_registry.tool_definitions()
                )

            now = datetime.now(timezone.utc).isoformat()
            await self.db.execute(
                "UPDATE subagent_tasks SET status = 'completed', result = ?, completed_at = ? "
                "WHERE id = ?",
                (response.content, now, subagent_id),
            )
        except TimeoutError:
            now = datetime.now(timezone.utc).isoformat()
            await self.db.execute(
                "UPDATE subagent_tasks SET status = 'failed', result = ?, completed_at = ? "
                "WHERE id = ?",
                ("Subagent timed out", now, subagent_id),
            )
        except Exception as e:
            now = datetime.now(timezone.utc).isoformat()
            await self.db.execute(
                "UPDATE subagent_tasks SET status = 'failed', result = ?, completed_at = ? "
                "WHERE id = ?",
                (f"Error: {e}", now, subagent_id),
            )
        finally:
            if self.tracer:
                try:
                    await self.tracer.emit(
                        "subagent_completed",
                        parent_conversation_id,
                        {"subagent_id": subagent_id, "instruction": instruction},
                    )
                except Exception:
                    logger.debug("Failed to emit subagent trace", exc_info=True)
            self._tasks.pop(subagent_id, None)

    def _build_restricted_registry(self) -> ToolRegistry:
        """Clone all tools except spawn_subagent to prevent recursive spawning."""
        restricted = ToolRegistry()
        for tool in self.tool_registry.list():
            if tool.name != "spawn_subagent":
                restricted.register(tool)
        return restricted

    async def get_completed_all(self) -> list[dict]:
        """Return all completed/failed tasks that have not been delivered yet."""
        return await self.db.fetch_all(
            "SELECT * FROM subagent_tasks "
            "WHERE status IN ('completed', 'failed') AND delivered_at IS NULL"
        )

    async def mark_delivered(self, subagent_id: str) -> None:
        """Mark a subagent task as delivered to the parent conversation."""
        now = datetime.now(timezone.utc).isoformat()
        await self.db.execute(
            "UPDATE subagent_tasks SET delivered_at = ? WHERE id = ?",
            (now, subagent_id),
        )
