from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from odigos.channels.base import UniversalMessage
from odigos.db import Database

if TYPE_CHECKING:
    from odigos.channels.base import ChannelRegistry
    from odigos.core.agent import Agent
    from odigos.core.goal_store import GoalStore
    from odigos.core.subagent import SubagentManager
    from odigos.core.trace import Tracer
    from odigos.providers.base import LLMProvider

logger = logging.getLogger(__name__)


class Heartbeat:
    """Background loop: fire reminders, work todos, idle-think about goals."""

    def __init__(
        self,
        db: Database,
        agent: Agent,
        channel_registry: ChannelRegistry,
        goal_store: GoalStore,
        provider: LLMProvider,
        interval: float = 30,
        max_todos_per_tick: int = 3,
        idle_think_interval: int = 900,
        tracer: Tracer | None = None,
        subagent_manager: SubagentManager | None = None,
    ) -> None:
        self.db = db
        self.agent = agent
        self.channel_registry = channel_registry
        self.goal_store = goal_store
        self.provider = provider
        self._interval = interval
        self._max_todos_per_tick = max_todos_per_tick
        self._idle_think_interval = idle_think_interval
        self._task: asyncio.Task | None = None
        self.tracer = tracer
        self.subagent_manager = subagent_manager
        self._last_idle: float = 0
        self.paused: bool = False

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())
        logger.info("Heartbeat started (interval: %.1fs)", self._interval)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            logger.info("Heartbeat stopped")

    async def _loop(self) -> None:
        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Heartbeat tick failed")
            await asyncio.sleep(self._interval)

    async def _tick(self) -> None:
        if self.paused:
            return

        did_work = False

        # Phase 1: Fire due reminders
        did_work |= await self._fire_reminders()

        # Phase 2: Work on pending todos
        did_work |= await self._work_todos()

        # Phase 3: Deliver subagent results
        did_work |= await self._deliver_subagent_results()

        # Phase 4: Idle thoughts (only if nothing ran above)
        if not did_work:
            await self._idle_think()

        if self.tracer:
            await self.tracer.emit("heartbeat_tick", None, {
                "did_work": did_work,
            })

    async def _fire_reminders(self) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        reminders = await self.db.fetch_all(
            "SELECT * FROM reminders WHERE status = 'pending' AND due_at <= ? "
            "ORDER BY due_at LIMIT 10",
            (now,),
        )
        if not reminders:
            return False

        for r in reminders:
            await self.db.execute(
                "UPDATE reminders SET status = 'fired' WHERE id = ?", (r["id"],)
            )
            if r.get("conversation_id"):
                await self._send_notification(
                    r["conversation_id"], f"Reminder: {r['description']}"
                )
            if r.get("recurrence"):
                await self._reinsert_recurring_reminder(r)
            logger.info("Fired reminder %s: %s", r["id"][:8], r["description"][:50])
        return True

    async def _work_todos(self) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        todos = await self.db.fetch_all(
            "SELECT * FROM todos WHERE status = 'pending' "
            "AND (scheduled_at IS NULL OR scheduled_at <= ?) "
            "ORDER BY created_at LIMIT ?",
            (now, self._max_todos_per_tick),
        )
        if not todos:
            return False

        for t in todos:
            asyncio.create_task(self._execute_todo(t))
        return True

    async def _execute_todo(self, todo: dict) -> None:
        todo_id = todo["id"]
        description = todo["description"] or ""

        try:
            message = UniversalMessage(
                id=str(uuid.uuid4()),
                channel="heartbeat",
                sender="system",
                content=description,
                timestamp=datetime.now(timezone.utc),
                metadata={"todo_id": todo_id},
            )
            result = await self.agent.handle_message(message)
            await self.goal_store.complete_todo(
                todo_id, result=result[:4000] if result else None
            )
            logger.info("Todo %s completed: %s", todo_id[:8], description[:50])

            if todo.get("conversation_id"):
                await self._send_notification(
                    todo["conversation_id"],
                    f"Todo completed: {description}\n\n{result}",
                )
        except Exception as e:
            await self.goal_store.fail_todo(todo_id, error=str(e))
            logger.error("Todo %s failed: %s", todo_id[:8], e)
            if todo.get("conversation_id"):
                await self._send_notification(
                    todo["conversation_id"],
                    f"Todo failed: {description}\n\n{e}",
                )

    async def _idle_think(self) -> None:
        now = time.monotonic()
        if now - self._last_idle < self._idle_think_interval:
            return
        self._last_idle = now

        goals = await self.goal_store.list_goals(status="active")
        if not goals:
            return

        goal_text = "\n".join(
            f"- [{g['id'][:8]}] {g['description']}"
            + (f" (progress: {g['progress_note']})" if g.get("progress_note") else "")
            for g in goals
        )

        try:
            response = await self.provider.complete(
                [
                    {
                        "role": "system",
                        "content": (
                            "You are reviewing your active goals during idle time. "
                            "If there's something useful you could do right now, respond with a JSON object: "
                            '{"todo": "description of work item"}. '
                            "If you have a progress observation, respond with: "
                            '{"note": "goal_id", "progress": "observation"}. '
                            'If nothing to do, respond with: {"idle": true}'
                        ),
                    },
                    {"role": "user", "content": f"Active goals:\n{goal_text}"},
                ],
                max_tokens=200,
                temperature=0.3,
            )
            logger.debug("Idle thought: %s", response.content[:100])
            await self._process_idle_response(response.content, goals)
        except Exception:
            logger.debug("Idle think failed", exc_info=True)

    async def _process_idle_response(self, content: str, goals: list[dict]) -> None:
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            # Try extracting JSON from markdown code blocks
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if not match:
                return
            try:
                parsed = json.loads(match.group())
            except (json.JSONDecodeError, TypeError):
                return
        if parsed.get("idle"):
            return
        if "todo" in parsed:
            await self.goal_store.create_todo(
                description=parsed["todo"], created_by="agent",
            )
            logger.info("Idle-think created todo: %s", parsed["todo"][:50])
        elif "note" in parsed and "progress" in parsed:
            goal_id_prefix = parsed["note"]
            for g in goals:
                if g["id"].startswith(goal_id_prefix):
                    await self.goal_store.update_goal(
                        g["id"],
                        progress_note=parsed["progress"],
                        reviewed_at=datetime.now(timezone.utc).isoformat(),
                    )
                    logger.info("Idle-think updated goal %s", g["id"][:8])
                    break

    async def _deliver_subagent_results(self) -> bool:
        """Deliver completed subagent results to their parent conversations."""
        if not self.subagent_manager:
            return False
        results = await self.subagent_manager.get_completed_all()
        if not results:
            return False
        for r in results:
            try:
                summary = (
                    f"[Subagent result] Task: {r['instruction'][:200]}\n\n"
                    f"Status: {r['status']}\n"
                    f"Result: {r['result']}"
                )
                conv_id = r["parent_conversation_id"]
                await self._send_notification(conv_id, summary[:4000])
                await self.subagent_manager.mark_delivered(r["id"])
                logger.info("Delivered subagent result %s to %s", r["id"], conv_id)
            except Exception:
                logger.exception("Failed to deliver subagent result %s", r["id"])
        return True

    async def _send_notification(self, conversation_id: str, text: str) -> None:
        try:
            channel = self.channel_registry.for_conversation(conversation_id)
            if channel:
                await channel.send_message(conversation_id, text[:4000])
        except Exception:
            logger.exception("Failed to send notification")

    async def _reinsert_recurring_reminder(self, reminder: dict) -> None:
        recurrence = reminder.get("recurrence", "")
        seconds_map = {"daily": 86400, "weekly": 604800, "hourly": 3600}
        if recurrence.startswith("every ") and recurrence.endswith("s"):
            try:
                interval = int(recurrence[6:-1])
            except ValueError:
                interval = 3600
        else:
            interval = seconds_map.get(recurrence, 3600)
        await self.goal_store.create_reminder(
            description=reminder["description"],
            due_seconds=interval,
            recurrence=recurrence,
            conversation_id=reminder.get("conversation_id"),
            created_by="heartbeat",
        )
