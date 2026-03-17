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
from odigos.core.prompt_loader import load_prompt
from odigos.db import Database

if TYPE_CHECKING:
    from odigos.channels.base import ChannelRegistry
    from odigos.core.agent import Agent
    from odigos.core.cron import CronManager
    from odigos.core.goal_store import GoalStore
    from odigos.core.evolution import EvolutionEngine
    from odigos.core.notifier import Notifier
    from odigos.core.strategist import Strategist
    from odigos.core.subagent import SubagentManager
    from odigos.core.trace import Tracer
    from odigos.core.agent_client import AgentClient
    from odigos.providers.base import LLMProvider

logger = logging.getLogger(__name__)

_IDLE_THINK_FALLBACK = (
    "You are reviewing your active goals during idle time. "
    "If there's something useful you could do right now, respond with a JSON object: "
    '{"todo": "description of work item"}. '
    "If you have a progress observation, respond with: "
    '{"note": "goal_id", "progress": "observation"}. '
    'If nothing to do, respond with: {"idle": true}'
)


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
        evolution_engine: EvolutionEngine | None = None,
        strategist: Strategist | None = None,
        agent_client: AgentClient | None = None,
        agent_role: str = "",
        agent_description: str = "",
        announce_interval: int = 60,
        background_model: str = "",
        cron_manager: CronManager | None = None,
        notifier: Notifier | None = None,
        ws_port: int = 8001,
    ) -> None:
        self.db = db
        self.agent = agent
        self.channel_registry = channel_registry
        self.goal_store = goal_store
        self.provider = provider
        self._background_model = background_model
        self._interval = interval
        self._max_todos_per_tick = max_todos_per_tick
        self._idle_think_interval = idle_think_interval
        self._task: asyncio.Task | None = None
        self.tracer = tracer
        self.subagent_manager = subagent_manager
        self.evolution_engine = evolution_engine
        self.strategist = strategist
        self._last_idle: float = 0
        self.paused: bool = False
        self.agent_client = agent_client
        self._agent_role = agent_role
        self._agent_description = agent_description
        self._announce_interval = announce_interval
        self._last_announce: float = 0
        self.cron_manager = cron_manager
        self.notifier = notifier
        self._ws_port = ws_port
        self._dream_tick_counter: int = 0
        self._dream_interval_ticks: int = 10

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

        # Phase 3b: Run due cron jobs
        did_work |= await self._run_cron_jobs()

        # Phase 4: Process inbound peer messages
        if self.agent_client:
            did_work |= await self._process_peer_messages()

        # Phase 5: Idle thoughts (only if nothing ran above)
        if not did_work:
            await self._idle_think()

        # Phase 6: Self-improvement cycle (runs when idle)
        if not did_work and self.evolution_engine:
            await self._run_evolution()

        # Phase 7: Peer announce + stale check
        if self.agent_client:
            await self._peer_maintenance()

        # Phase 8: User profile dreaming (every N ticks)
        self._dream_tick_counter += 1
        if self._dream_tick_counter >= self._dream_interval_ticks:
            self._dream_tick_counter = 0
            await self._dream_analyze_user()

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

    async def _process_peer_messages(self) -> bool:
        """Phase 4: Process unhandled inbound messages from peer agents.

        When a peer agent sends a message (help request, status update, task
        delegation, etc.), this phase picks it up and routes it through the
        agent for a response. This enables proactive cross-agent communication.
        """
        messages = await self.agent_client.get_unprocessed_inbound(limit=3)
        if not messages:
            return False

        for msg in messages:
            peer = msg["peer_name"]
            msg_type = msg["message_type"]
            try:
                content_raw = msg["content"]
                payload = json.loads(content_raw) if isinstance(content_raw, str) else content_raw
                message_text = payload.get("content", "") if isinstance(payload, dict) else str(payload)
            except (json.JSONDecodeError, TypeError):
                message_text = str(msg["content"])

            logger.info(
                "Processing inbound %s from peer %s: %s",
                msg_type, peer, message_text[:100],
            )

            # Route through the agent for a response
            try:
                peer_msg = UniversalMessage(
                    id=str(uuid.uuid4()),
                    channel="peer",
                    sender=peer,
                    content=f"[Peer message from {peer} (type: {msg_type})]\n\n{message_text}",
                    timestamp=datetime.now(timezone.utc),
                    metadata={"peer_name": peer, "message_type": msg_type},
                )
                agent_response = await self.agent.handle_message(peer_msg)

                # Send response back to the peer
                if agent_response and self.agent_client:
                    await self.agent_client.send(
                        peer,
                        payload={"content": agent_response},
                        message_type="message",
                        correlation_id=msg.get("response_to"),
                    )
            except Exception:
                logger.warning("Failed to process peer message from %s", peer, exc_info=True)

            await self.agent_client.mark_processed(msg["message_id"])

        return True

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
            idle_kwargs: dict = {"max_tokens": 200, "temperature": 0.3}
            if self._background_model:
                idle_kwargs["model"] = self._background_model
            response = await self.provider.complete(
                [
                    {
                        "role": "system",
                        "content": load_prompt("heartbeat_idle.md", _IDLE_THINK_FALLBACK),
                    },
                    {"role": "user", "content": f"Active goals:\n{goal_text}"},
                ],
                **idle_kwargs,
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

    async def _run_cron_jobs(self) -> bool:
        """Run due cron entries and notify with results."""
        if not self.cron_manager:
            return False
        due_entries = await self.cron_manager.tick()
        if not due_entries:
            return False

        for entry in due_entries:
            try:
                message = UniversalMessage(
                    id=str(uuid.uuid4()),
                    channel="cron",
                    sender="system",
                    content=entry.action,
                    timestamp=datetime.now(timezone.utc),
                    metadata={
                        "cron_entry_id": entry.id,
                        "cron_entry_name": entry.name,
                    },
                )
                result = await self.agent.handle_message(message)
                await self.cron_manager.mark_run(entry.id)
                logger.info("Cron job '%s' completed: %s", entry.name, (result or "")[:80])

                # Notify with the result
                if self.notifier:
                    await self.notifier.notify(
                        title=f"Cron: {entry.name}",
                        body=result[:4000] if result else "(no output)",
                        conversation_id=entry.conversation_id,
                    )
                elif entry.conversation_id:
                    await self._send_notification(
                        entry.conversation_id,
                        f"Cron '{entry.name}' result:\n\n{result}",
                    )
            except Exception:
                logger.exception("Cron job '%s' failed", entry.name)
                await self.cron_manager.mark_run(entry.id)
        return True

    async def _run_evolution(self) -> None:
        """Phase 5: Score past actions, manage trials, run strategist."""
        try:
            scored = await self.evolution_engine.score_past_actions(limit=3)
            if scored:
                logger.debug("Evolution: scored %d past actions", scored)

            result = await self.evolution_engine.check_active_trial()
            if result and result != "continue":
                logger.info("Evolution: trial %s", result)

            # Run strategist if enough new evaluations
            if self.strategist:
                if await self.strategist.should_run():
                    analysis = await self.strategist.analyze()
                    if analysis:
                        logger.info("Strategist: analyzed, %d hypotheses",
                                    len(analysis.get("hypotheses", [])))
        except Exception:
            logger.debug("Evolution cycle failed", exc_info=True)

    async def _peer_maintenance(self) -> None:
        """Phase 6: Announce self to peers, flush outbox, mark stale peers offline.

        Inert when solo: skips entirely if no peers configured and no online peers in registry.
        """
        # Inert-when-solo guard
        if not self.agent_client.list_peer_names():
            online = await self.db.fetch_one(
                "SELECT 1 FROM agent_registry WHERE status = 'online' LIMIT 1"
            )
            if not online:
                return

        now = time.monotonic()
        try:
            # Announce on schedule
            if now - self._last_announce >= self._announce_interval:
                self._last_announce = now
                await self.agent_client.broadcast_announce(
                    role=self._agent_role,
                    description=self._agent_description,
                    ws_port=self._ws_port,
                )
                await self.agent_client.mark_stale_peers()

            # Always try to flush outbox
            await self.agent_client.flush_outbox()
        except Exception:
            logger.debug("Peer maintenance failed", exc_info=True)

    async def _dream_analyze_user(self) -> None:
        """Analyze recent conversations to build/update the user profile."""
        _PROFILE_PROMPT_FALLBACK = (
            "Analyze recent conversations and update the user profile. "
            "Respond with JSON containing: communication_style, expertise_areas, "
            "preferences, recurring_topics, correction_patterns, summary."
        )
        try:
            # Fetch current profile
            profile = await self.db.fetch_one(
                "SELECT * FROM user_profile WHERE id = 'owner'"
            )
            if not profile:
                return

            # Check if enough new conversations since last analysis
            total_convs = await self.db.fetch_one(
                "SELECT COUNT(*) as cnt FROM conversations"
            )
            conv_count = total_convs["cnt"] if total_convs else 0
            last_count = profile.get("conversation_count") or 0
            if conv_count - last_count < 5:
                return

            # Fetch last 20 conversations with their messages
            convs = await self.db.fetch_all(
                "SELECT id, title FROM conversations ORDER BY created_at DESC LIMIT 20"
            )
            if not convs:
                return

            conv_texts = []
            for c in convs:
                msgs = await self.db.fetch_all(
                    "SELECT role, content FROM messages WHERE conversation_id = ? "
                    "ORDER BY timestamp ASC LIMIT 20",
                    (c["id"],),
                )
                if msgs:
                    title = c.get("title") or c["id"][:8]
                    lines = [f"### {title}"]
                    for m in msgs:
                        content = (m["content"] or "")[:500]
                        lines.append(f"{m['role']}: {content}")
                    conv_texts.append("\n".join(lines))

            if not conv_texts:
                return

            # Build current profile text
            current_profile = (
                f"Communication style: {profile.get('communication_style') or '(unknown)'}\n"
                f"Expertise: {profile.get('expertise_areas') or '(unknown)'}\n"
                f"Preferences: {profile.get('preferences') or '(unknown)'}\n"
                f"Recurring topics: {profile.get('recurring_topics') or '(unknown)'}\n"
                f"Correction patterns: {profile.get('correction_patterns') or '(unknown)'}\n"
                f"Summary: {profile.get('summary') or '(none yet)'}"
            )

            prompt_template = load_prompt("user_profile.md", _PROFILE_PROMPT_FALLBACK)
            prompt_text = prompt_template.format(
                current_profile=current_profile,
                conversations="\n\n".join(conv_texts[:10]),
            )

            dream_kwargs: dict = {"max_tokens": 800, "temperature": 0.3}
            if self._background_model:
                dream_kwargs["model"] = self._background_model

            response = await self.provider.complete(
                [
                    {"role": "system", "content": "You are a user profiling assistant. Respond only with valid JSON."},
                    {"role": "user", "content": prompt_text},
                ],
                **dream_kwargs,
            )

            # Parse the response
            text = response.content.strip()
            # Strip markdown code fences if present
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*", "", text)
                text = re.sub(r"\s*```$", "", text)
            parsed = json.loads(text)

            now = datetime.now(timezone.utc).isoformat()
            await self.db.execute(
                "UPDATE user_profile SET "
                "communication_style = ?, expertise_areas = ?, preferences = ?, "
                "recurring_topics = ?, correction_patterns = ?, summary = ?, "
                "last_analyzed_at = ?, conversation_count = ? "
                "WHERE id = 'owner'",
                (
                    parsed.get("communication_style", ""),
                    parsed.get("expertise_areas", ""),
                    parsed.get("preferences", ""),
                    parsed.get("recurring_topics", ""),
                    parsed.get("correction_patterns", ""),
                    parsed.get("summary", ""),
                    now,
                    conv_count,
                ),
            )
            logger.info("User profile updated (analyzed %d conversations)", len(conv_texts))
        except Exception:
            logger.debug("Dream user profile analysis failed", exc_info=True)

    async def _send_notification(self, conversation_id: str, text: str) -> None:
        try:
            channel = self.channel_registry.for_conversation(conversation_id)
            if channel:
                await channel.send_message(conversation_id, text[:4000])
        except Exception:
            logger.exception("Failed to send notification")

    async def _reinsert_recurring_reminder(self, reminder: dict) -> None:
        recurrence = reminder.get("recurrence", "")
        interval = _parse_recurrence_seconds(recurrence)
        await self.goal_store.create_reminder(
            description=reminder["description"],
            due_seconds=interval,
            recurrence=recurrence,
            conversation_id=reminder.get("conversation_id"),
            created_by="heartbeat",
        )


def _parse_recurrence_seconds(recurrence: str) -> int:
    """Parse a recurrence string into seconds until next occurrence.

    Supports: 'daily', 'weekly', 'hourly', 'every Ns', and natural
    language like 'every 2 hours', 'every 30 minutes', 'every 3 days'.
    Falls back to 3600 (1 hour) for unrecognized patterns.
    """
    from dateutil.relativedelta import relativedelta

    simple = {"daily": 86400, "weekly": 604800, "hourly": 3600}
    if recurrence in simple:
        return simple[recurrence]

    # "every Ns" — raw seconds
    if recurrence.startswith("every ") and recurrence.endswith("s"):
        try:
            return int(recurrence[6:-1])
        except ValueError:
            pass

    # Natural language: "every N unit(s)"
    match = re.match(r"every\s+(\d+)\s+(\w+)", recurrence, re.IGNORECASE)
    if match:
        count = int(match.group(1))
        unit = match.group(2).lower().rstrip("s")  # normalize plural
        unit_map = {"second": 1, "minute": 60, "hour": 3600, "day": 86400, "week": 604800}
        if unit in unit_map:
            return count * unit_map[unit]
        # Use relativedelta for month-level intervals
        if unit == "month":
            delta = relativedelta(months=count)
            now = datetime.now(timezone.utc)
            future = now + delta
            return int((future - now).total_seconds())

    return 3600
