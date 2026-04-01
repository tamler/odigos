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
from odigos.core.json_utils import parse_json_response
from odigos.core.content_filter import ContentFilter
from odigos.core.llm_prompt import run_prompt
from odigos.core.prompt_loader import load_prompt
from odigos.db import Database

_peer_filter = ContentFilter()

if TYPE_CHECKING:
    from odigos.channels.base import ChannelRegistry
    from odigos.core.agent import Agent
    from odigos.core.cron import CronManager
    from odigos.core.goal_store import GoalStore
    from odigos.core.evolution import EvolutionEngine
    from odigos.core.notifier import Notifier
    from odigos.core.scheduler import Scheduler
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
        scheduler: Scheduler | None = None,
        ws_port: int = 8001,
        settings=None,
    ) -> None:
        self.db = db
        self.settings = settings
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
        self.scheduler = scheduler
        self._ws_port = ws_port
        self._dream_tick_counter: int = 0
        self._dream_interval_ticks: int = 10
        self._experience_tick_counter: int = 0
        self._experience_interval_ticks: int = 20
        self._outcome_tick_counter: int = 0
        self._outcome_interval_ticks: int = 10
        self._email_tick_counter: int = 0
        self._email_config = None  # Set from main.py if email is configured
        self._update_tick_counter: int = 0
        self._nudge_tick_counter: int = 0
        self._nudge_interval_ticks: int = 20
        self._followup_tick_counter: int = 0
        self._followup_interval_ticks: int = 30
        self._quota_tick_counter: int = 0

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

        # Phase 0: Morning briefing (once per day)
        await self._maybe_send_briefing()

        # Phase 1: Process scheduled tasks (unified reminders + cron)
        did_work |= await self._process_scheduled_tasks()

        # Phase 1b: Fire legacy reminders (old table, for backward compat)
        did_work |= await self._fire_reminders()

        # Phase 2: Work on pending todos
        did_work |= await self._work_todos()

        # Phase 3: Deliver subagent results
        did_work |= await self._deliver_subagent_results()

        # Phase 3b: Run legacy cron jobs (old table, for backward compat)
        did_work |= await self._run_cron_jobs()

        # Phase 4: Process inbound peer messages
        if self.agent_client:
            did_work |= await self._process_peer_messages()

        # Phase 4b: Check email inbox (if configured)
        _email_cfg = getattr(self, "_email_config", None)
        if _email_cfg and _email_cfg.enabled:
            if not hasattr(self, "_email_tick_counter"):
                self._email_tick_counter = 0
            self._email_tick_counter += 1
            interval = _email_cfg.check_interval_ticks or 10
            if self._email_tick_counter >= interval:
                self._email_tick_counter = 0
                did_work |= await self._check_email()

        # Phase 4c: Proactive nudges (stale tasks, overdue goals)
        self._nudge_tick_counter += 1
        if self._nudge_tick_counter >= self._nudge_interval_ticks:
            self._nudge_tick_counter = 0
            did_work |= await self._send_nudges()

        # Phase 4d: Follow-up reminders (user commitments)
        self._followup_tick_counter += 1
        if self._followup_tick_counter >= self._followup_interval_ticks:
            self._followup_tick_counter = 0
            did_work |= await self._check_followups()

        # Phase 4e: Proactive plan execution (work on in-progress plans during idle)
        if not did_work:
            did_work |= await self._work_in_progress_plans()

        # Phase 5: Idle thoughts (only if nothing ran above)
        if not did_work:
            await self._idle_think()

        # Phase 6: Self-improvement cycle (runs when idle)
        if not did_work and self.evolution_engine:
            await self._run_evolution()

        # Phase 7: Peer announce + stale check
        if self.agent_client:
            await self._peer_maintenance()

        # Phase 8: User profile dreaming (every N ticks, only when idle)
        if not did_work:
            self._dream_tick_counter += 1
            if self._dream_tick_counter >= self._dream_interval_ticks:
                self._dream_tick_counter = 0
                await self._dream_analyze_user()

        # Phase 9: Experience extraction (every N ticks, only when idle)
        if not did_work:
            self._experience_tick_counter += 1
            if self._experience_tick_counter >= self._experience_interval_ticks:
                self._experience_tick_counter = 0
                await self._extract_experiences()

        # Phase 10: Outcome evaluation for completed plans (every N ticks, only when idle)
        if not did_work:
            self._outcome_tick_counter += 1
            if self._outcome_tick_counter >= self._outcome_interval_ticks:
                self._outcome_tick_counter = 0
                await self._evaluate_plan_outcomes()

        # Phase 11: Auto-update check (if enabled)
        _update_cfg = self.settings.auto_update if self.settings else None
        if _update_cfg and _update_cfg.enabled:
            self._update_tick_counter += 1
            if self._update_tick_counter >= _update_cfg.check_interval_ticks:
                self._update_tick_counter = 0
                await self._check_for_updates()

        # Phase 12: Storage quota check (every 60 ticks ~= 30min at 30s interval)
        self._quota_tick_counter += 1
        if self._quota_tick_counter >= 60:
            self._quota_tick_counter = 0
            await self._check_storage_quota()

        if self.tracer:
            await self.tracer.emit("heartbeat_tick", None, {
                "did_work": did_work,
            })

    async def _maybe_send_briefing(self) -> None:
        """Send morning briefing once per day if enabled."""
        try:
            # Check if briefing is enabled in settings
            if self.settings:
                enabled = self.settings.heartbeat.morning_briefing
                if not enabled:
                    return

            from odigos.core.briefing import should_send_briefing, compose_briefing, mark_briefing_sent

            if not await should_send_briefing(self.db):
                return

            logger.info("Composing morning briefing")
            model = self._background_model or ""
            content = await compose_briefing(
                self.db, self.provider, settings=self.settings, model=model,
            )

            # Send via notifier to all channels
            if self.notifier:
                await self.notifier.notify(
                    title="Morning Briefing",
                    body=content,
                )

            # Also send as a structured WebSocket message for the frontend
            web_channel = self.channel_registry.get("web") if self.channel_registry else None
            if web_channel and hasattr(web_channel, 'broadcast'):
                await web_channel.broadcast({
                    "type": "morning_briefing",
                    "content": content,
                })

            await mark_briefing_sent(self.db)
            logger.info("Morning briefing sent")
        except Exception:
            logger.debug("Morning briefing failed", exc_info=True)

    async def _check_email(self) -> bool:
        """Check inbox for new emails and notify the user."""
        try:
            from odigos.tools.email import CheckEmailTool
            tool = CheckEmailTool(email_config=self._email_config)
            result = await tool.execute({"limit": 5, "unread_only": True})
            if not result.success:
                return False
            if "No new emails" in result.data:
                return False

            # Notify user about new emails
            if self.notifier:
                # Count emails from the result
                email_count = result.data.count("From:")
                if email_count > 0:
                    await self.notifier.notify(
                        title="New Email",
                        body=f"You have {email_count} new email(s). Ask me to read them.",
                        priority="normal",
                    )
                    logger.info("Email check: %d new message(s)", email_count)
                    return True
        except Exception:
            logger.debug("Email check failed", exc_info=True)
        return False

    async def _send_nudges(self) -> bool:
        """Check for stale tasks and overdue goals, notify user."""
        try:
            from odigos.core.nudger import (
                format_nudge_notification,
                get_nudge_items,
            )

            nudges = await get_nudge_items(self.db)
            if not nudges:
                return False

            msg = format_nudge_notification(nudges)
            if msg and self.notifier:
                await self.notifier.notify(
                    title="Reminder",
                    body=msg,
                    priority="normal",
                )
                return True
        except Exception:
            logger.debug("Nudge check failed", exc_info=True)
        return False

    async def _check_followups(self) -> bool:
        """Check for user commitments that might need follow-up."""
        try:
            from odigos.core.followups import (
                find_untracked_commitments,
                format_followup_notification,
            )
            commitments = await find_untracked_commitments(self.db)
            if not commitments:
                return False
            msg = format_followup_notification(commitments)
            if msg and self.notifier:
                await self.notifier.notify(
                    title="Follow-up",
                    body=msg,
                    priority="low",
                )
                return True
        except Exception:
            logger.debug(
                "Follow-up check failed", exc_info=True,
            )
        return False

    async def _dispatch_as_subagent(self, instruction: str, conversation_id: str = "") -> str | None:
        """Run a heartbeat task as an internal subagent for multi-step reasoning."""
        if not self.subagent_manager:
            return None
        try:
            subagent_id = await self.subagent_manager.spawn(
                instruction=instruction,
                parent_conversation_id=conversation_id or "heartbeat",
            )
            return subagent_id
        except Exception:
            logger.warning("Subagent dispatch failed", exc_info=True)
            return None

    async def _process_scheduled_tasks(self) -> bool:
        """Process due tasks from the unified scheduled_tasks table."""
        if not self.scheduler:
            return False
        due_tasks = await self.scheduler.get_due_tasks()
        if not due_tasks:
            return False

        for task in due_tasks:
            try:
                action_type = task.get("action_type", "remind")
                if action_type == "remind":
                    if self.notifier:
                        await self.notifier.notify(
                            title="Reminder",
                            body=task["action"],
                            conversation_id=task.get("conversation_id"),
                        )
                    elif task.get("conversation_id"):
                        await self._send_notification(
                            task["conversation_id"],
                            f"Reminder: {task['action']}",
                        )
                elif action_type == "execute":
                    message = UniversalMessage(
                        id=str(uuid.uuid4()),
                        channel="scheduler",
                        sender="system",
                        content=task["action"],
                        timestamp=datetime.now(timezone.utc),
                        metadata={
                            "scheduled_task_id": task["id"],
                            "scheduled_task_name": task["name"],
                        },
                    )
                    result = await self.agent.handle_message(message)
                    if self.notifier:
                        await self.notifier.notify(
                            title=f"Scheduled: {task['name']}",
                            body=result[:4000] if result else "(no output)",
                            conversation_id=task.get("conversation_id"),
                        )
                elif action_type == "notify":
                    if self.notifier:
                        await self.notifier.notify(
                            title="Scheduled",
                            body=task["action"],
                            conversation_id=task.get("conversation_id"),
                        )
                    elif task.get("conversation_id"):
                        await self._send_notification(
                            task["conversation_id"],
                            task["action"],
                        )
            except Exception:
                logger.exception(
                    "Scheduled task '%s' (%s) failed", task["name"], task["id"][:8]
                )

            await self.scheduler.mark_completed(task["id"])
            logger.info(
                "Processed scheduled task '%s' (type=%s, action_type=%s)",
                task["name"], task["type"], task.get("action_type", "remind"),
            )
        return True

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
        goal_id = todo.get("goal_id")

        try:
            metadata = {"todo_id": todo_id}
            if goal_id:
                metadata["goal_id"] = goal_id
            message = UniversalMessage(
                id=str(uuid.uuid4()),
                channel="heartbeat",
                sender="system",
                content=description,
                timestamp=datetime.now(timezone.utc),
                metadata=metadata,
            )
            result = await self.agent.handle_message(message)
            await self.goal_store.complete_todo(
                todo_id, result=result[:4000] if result else None
            )
            logger.info("Todo %s completed: %s", todo_id[:8], description[:50])

            # Session persistence: log idle work for future context
            await self._log_heartbeat_session(
                goal_id=goal_id, todo_id=todo_id,
                summary=f"Completed: {description[:200]}. Result: {(result or '')[:300]}",
            )

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

            # Skip system messages that slipped through
            if msg_type in ("registry_announce", "status_ping", "status_pong"):
                await self.agent_client.mark_processed(msg["message_id"])
                continue

            try:
                content_raw = msg["content"]
                payload = json.loads(content_raw) if isinstance(content_raw, str) else content_raw
                message_text = payload.get("content", "") if isinstance(payload, dict) else str(payload)
            except (json.JSONDecodeError, TypeError):
                message_text = str(msg["content"])

            # Skip empty or JSON-only messages (likely system data)
            if not message_text.strip() or (message_text.strip().startswith("{") and message_text.strip().endswith("}")):
                await self.agent_client.mark_processed(msg["message_id"])
                logger.debug("Skipped non-content peer message from %s: %s", peer, msg_type)
                continue

            # Re-scan for injection on replay (annotation may have been lost in DB round-trip)
            scan = _peer_filter.scan(message_text)
            if scan.risk_level == "high":
                logger.warning("Blocked peer message from %s: high injection risk", peer)
                await self.agent_client.mark_processed(msg["message_id"])
                continue
            message_text = scan.sanitized_text

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

    _plan_fail_count: int = 0
    _MAX_PLAN_RETRIES: int = 3  # stop trying after 3 consecutive failures

    async def _work_in_progress_plans(self) -> bool:
        """Phase 4e: Pick up in-progress plans and execute the next pending step."""
        if self._plan_fail_count >= self._MAX_PLAN_RETRIES:
            return False  # Stop retrying stuck plans

        try:
            row = await self.db.fetch_one(
                "SELECT id, conversation_id, steps, goal FROM task_plans "
                "WHERE status = 'in_progress' "
                "ORDER BY updated_at ASC LIMIT 1",
            )
            if not row:
                self._plan_fail_count = 0  # Reset on no plans
                return False

            steps = json.loads(row["steps"])
            next_step = None
            for s in steps:
                if s.get("status") in (None, "pending"):
                    next_step = s
                    break
                for sub in s.get("substeps", []):
                    if sub.get("status") in (None, "pending"):
                        next_step = sub
                        break
                if next_step:
                    break

            if not next_step:
                # Check for stuck in_progress steps (reset them to pending)
                has_stuck = False
                for s in steps:
                    if s.get("status") == "in_progress":
                        s["status"] = "pending"
                        has_stuck = True
                    for sub in s.get("substeps", []):
                        if sub.get("status") == "in_progress":
                            sub["status"] = "pending"
                            has_stuck = True
                if has_stuck:
                    await self.db.execute(
                        "UPDATE task_plans SET steps = ?, updated_at = ? WHERE id = ?",
                        (json.dumps(steps), datetime.now(timezone.utc).isoformat(), row["id"]),
                    )
                    logger.info("Reset stuck in_progress steps for plan %s", row["id"][:8])
                    return False

                # All steps truly done, mark plan complete
                await self.db.execute(
                    "UPDATE task_plans SET status = 'done', updated_at = ? WHERE id = ?",
                    (datetime.now(timezone.utc).isoformat(), row["id"]),
                )
                return False

            # Execute the next step using the original conversation context
            step_desc = next_step.get("task", "")
            step_num = str(next_step.get("step", ""))
            plan_id = row["id"]
            conversation_id = row["conversation_id"]
            goal = row.get("goal")

            content = (
                f"Continue working on the plan. Execute step {step_num}: {step_desc}\n"
                f"When done, use update_plan to mark step {step_num} as done with your result."
            )

            metadata = {"plan_id": plan_id, "step": step_num}
            if goal:
                metadata["goal_id"] = goal

            message = UniversalMessage(
                id=str(uuid.uuid4()),
                channel="heartbeat",
                sender="system",
                content=content,
                timestamp=datetime.now(timezone.utc),
                metadata=metadata,
            )

            # Mark step as in_progress
            next_step["status"] = "in_progress"
            await self.db.execute(
                "UPDATE task_plans SET steps = ?, updated_at = ? WHERE id = ?",
                (json.dumps(steps), datetime.now(timezone.utc).isoformat(), plan_id),
            )

            result = await self.agent.handle_message(message)

            # Detect LLM failure responses
            _FAIL_MARKERS = ("couldn't process", "having trouble reaching", "ran out of time", "went wrong")
            if result and any(m in result.lower() for m in _FAIL_MARKERS):
                self._plan_fail_count += 1
                logger.warning("Plan step failed (LLM error): %s (%d/%d)", result[:100], self._plan_fail_count, self._MAX_PLAN_RETRIES)
                return False

            await self._log_heartbeat_session(
                goal_id=goal, plan_id=plan_id,
                conversation_id=conversation_id,
                summary=f"Plan step {step_num}: {step_desc[:100]}. Result: {(result or '')[:300]}",
            )

            logger.info("Proactive plan step %s executed for plan %s", step_num, plan_id[:8])
            self._plan_fail_count = 0
            return True
        except Exception:
            self._plan_fail_count += 1
            logger.warning("Proactive plan failed (%d/%d)", self._plan_fail_count, self._MAX_PLAN_RETRIES)
            return False

    async def _log_heartbeat_session(
        self,
        goal_id: str | None = None,
        todo_id: str | None = None,
        plan_id: str | None = None,
        conversation_id: str | None = None,
        summary: str = "",
    ) -> None:
        """Log autonomous work for session persistence across heartbeat cycles."""
        try:
            await self.db.execute(
                "INSERT INTO heartbeat_sessions "
                "(id, goal_id, todo_id, plan_id, conversation_id, summary, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), goal_id, todo_id, plan_id, conversation_id,
                 summary[:2000], datetime.now(timezone.utc).isoformat()),
            )
        except Exception:
            logger.debug("Could not log heartbeat session", exc_info=True)

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

        # Augment with idle research opportunities
        research_context = ""
        try:
            from odigos.core.idle_research import (
                find_research_opportunities,
                format_research_prompt,
            )
            opportunities = await find_research_opportunities(
                self.db,
            )
            research_context = format_research_prompt(opportunities)
        except Exception:
            logger.debug(
                "Idle research lookup failed", exc_info=True,
            )

        user_content = f"Active goals:\n{goal_text}"
        if research_context:
            user_content += f"\n\n{research_context}"

        try:
            from odigos.core.llm_prompt import call_llm
            response = await call_llm(
                self.provider,
                [
                    {
                        "role": "system",
                        "content": load_prompt("heartbeat_idle.md", _IDLE_THINK_FALLBACK),
                    },
                    {"role": "user", "content": user_content},
                ],
                max_tokens=200, temperature=0.3,
                model=self._background_model or None,
                log_name="idle_think",
            )
            if not response:
                return
            logger.debug("Idle thought: %s", response.content[:100])
            await self._process_idle_response(response.content, goals)
        except Exception:
            logger.debug("Idle think failed", exc_info=True)

    async def _process_idle_response(self, content: str, goals: list[dict]) -> None:
        parsed = parse_json_response(content)
        if parsed is None:
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
                conversation_id = r["parent_conversation_id"]
                await self._send_notification(conversation_id, summary[:4000])
                await self.subagent_manager.mark_delivered(r["id"])
                logger.info("Delivered subagent result %s to %s", r["id"], conversation_id)
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
        """Phase 5: Score past actions, manage trials, run strategist, rollup domain perf."""
        try:
            scored = await self.evolution_engine.score_past_actions(limit=3)
            if scored:
                logger.debug("Evolution: scored %d past actions", scored)

            result = await self.evolution_engine.check_active_trial()
            if result and result != "continue":
                logger.info("Evolution: trial %s", result)

            # Domain performance rollup (cheap, runs every evolution cycle)
            await self.evolution_engine.rollup_domain_performance()

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

    async def _check_for_updates(self) -> None:
        """Check for code updates and optionally apply them."""
        try:
            from odigos.core.updater import (
                apply_update,
                check_for_updates,
                restart_service,
            )

            update_cfg = self.settings.auto_update
            info = await asyncio.to_thread(
                check_for_updates, update_cfg.branch,
            )
            if not info:
                return

            logger.info(
                "Update available: %s -> %s (%d commits)",
                info["local"],
                info["remote"],
                info["commits"],
            )

            if update_cfg.auto_apply:
                success, msg = await asyncio.to_thread(
                    apply_update, update_cfg.branch,
                )
                if success:
                    logger.info(
                        "Update applied successfully, restarting...",
                    )
                    if self.notifier:
                        await self.notifier.notify(
                            title="Update Applied",
                            body=(
                                f"Applied {info['commits']} new "
                                f"commit(s). Restarting now."
                            ),
                            priority="normal",
                        )
                    # Give notification time to deliver
                    await asyncio.sleep(2)
                    await asyncio.to_thread(restart_service)
                else:
                    logger.error("Update failed: %s", msg)
                    if self.notifier:
                        await self.notifier.notify(
                            title="Update Failed",
                            body=(
                                f"Auto-update failed: "
                                f"{msg[:200]}"
                            ),
                            priority="high",
                        )
            else:
                # Notify only
                if self.notifier:
                    await self.notifier.notify(
                        title="Update Available",
                        body=(
                            f"{info['commits']} new commit(s) "
                            f"available. Latest: "
                            f"{info['log'][:200]}"
                        ),
                        priority="normal",
                    )
        except Exception:
            logger.debug("Update check failed", exc_info=True)

    async def _check_storage_quota(self) -> None:
        """Check data/ directory size against configured quota limits."""
        try:
            from pathlib import Path

            quota = self.settings.storage if self.settings else None
            warn_gb = quota.warn_gb if quota else 10.0
            cap_gb = quota.cap_gb if quota else 12.0

            data_dir = Path("data")
            if not data_dir.exists():
                return

            def _calc_size() -> int:
                return sum(
                    f.stat(follow_symlinks=False).st_size
                    for f in data_dir.rglob("*")
                    if f.is_file() and not f.is_symlink()
                )

            total_bytes = await asyncio.to_thread(_calc_size)
            total_gb = total_bytes / (1024 ** 3)

            if total_gb >= cap_gb:
                logger.warning("Storage quota exceeded: %.2f GB / %.1f GB cap", total_gb, cap_gb)
                if self.notifier:
                    await self.notifier.notify(
                        title="Storage Limit Reached",
                        body=(
                            f"Storage usage is {total_gb:.1f} GB, exceeding the "
                            f"{cap_gb:.0f} GB limit. File uploads and image generation "
                            f"may be blocked until space is freed."
                        ),
                        priority="high",
                    )
            elif total_gb >= warn_gb:
                logger.info("Storage warning: %.2f GB / %.1f GB warn threshold", total_gb, warn_gb)
                if self.notifier:
                    await self.notifier.notify(
                        title="Storage Warning",
                        body=(
                            f"Storage usage is {total_gb:.1f} GB, approaching the "
                            f"{cap_gb:.0f} GB limit. Consider cleaning up old files."
                        ),
                        priority="normal",
                    )

            # Store current usage for tools to check before writing
            await self.db.execute(
                """INSERT OR REPLACE INTO kv (key, value) VALUES ('storage_usage_gb', ?)""",
                (f"{total_gb:.4f}",),
            )
        except Exception:
            logger.debug("Storage quota check failed", exc_info=True)

    async def _dream_analyze_user(self) -> None:
        """Analyze recent conversations to build/update the user profile."""
        _PROFILE_PROMPT_FALLBACK = (
            "Analyze recent conversations and update the user profile. "
            "Respond with JSON containing: communication_style, expertise_areas, "
            "preferences, recurring_topics, correction_patterns, summary, "
            "activity_pattern, engagement_trend, unmet_needs, relationship_stage."
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

            # Fetch last 20 conversations with their messages (single query)
            convs = await self.db.fetch_all(
                "SELECT id, title FROM conversations ORDER BY created_at DESC LIMIT 20"
            )
            if not convs:
                return

            conv_ids = [c["id"] for c in convs]
            placeholders = ",".join("?" for _ in conv_ids)
            all_msgs = await self.db.fetch_all(
                f"SELECT conversation_id, role, content FROM messages "
                f"WHERE conversation_id IN ({placeholders}) "
                f"ORDER BY timestamp ASC",
                tuple(conv_ids),
            )

            # Group messages by conversation, keeping only first 20 per conv
            msgs_by_conv: dict[str, list] = {}
            for m in all_msgs:
                cid = m["conversation_id"]
                bucket = msgs_by_conv.setdefault(cid, [])
                if len(bucket) < 20:
                    bucket.append(m)

            conv_texts = []
            for c in convs:
                msgs = msgs_by_conv.get(c["id"], [])
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

            parsed = await run_prompt(
                self.provider,
                "user_profile.md",
                {
                    "current_profile": current_profile,
                    "conversations": "\n\n".join(conv_texts[:10]),
                },
                _PROFILE_PROMPT_FALLBACK,
                model=self._background_model or None,
                max_tokens=800,
                temperature=0.3,
            )
            if parsed is None:
                return

            now = datetime.now(timezone.utc).isoformat()
            try:
                await self.db.execute(
                    "UPDATE user_profile SET "
                    "communication_style = ?, expertise_areas = ?, preferences = ?, "
                    "recurring_topics = ?, correction_patterns = ?, summary = ?, "
                    "activity_pattern = ?, engagement_trend = ?, unmet_needs = ?, "
                    "relationship_stage = ?, "
                    "last_analyzed_at = ?, conversation_count = ? "
                    "WHERE id = 'owner'",
                    (
                        parsed.get("communication_style", ""),
                        parsed.get("expertise_areas", ""),
                        parsed.get("preferences", ""),
                        parsed.get("recurring_topics", ""),
                        parsed.get("correction_patterns", ""),
                        parsed.get("summary", ""),
                        parsed.get("activity_pattern", ""),
                        parsed.get("engagement_trend", ""),
                        parsed.get("unmet_needs", ""),
                        parsed.get("relationship_stage", "new"),
                        now,
                        conv_count,
                    ),
                )
            except Exception:
                # New columns may not exist yet; fall back to original set
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

            # Process extracted facts
            facts = parsed.get("facts", [])
            if facts and isinstance(facts, list):
                inserted = 0
                for item in facts:
                    if not isinstance(item, dict) or not item.get("fact"):
                        continue
                    fact_text = item["fact"].strip()
                    category = item.get("category", "general")
                    if category not in (
                        "personal", "professional", "preference",
                        "technical", "location", "general",
                    ):
                        category = "general"
                    # Skip if an identical fact already exists
                    existing = await self.db.fetch_one(
                        "SELECT id FROM user_facts WHERE fact = ?", (fact_text,)
                    )
                    if existing:
                        continue
                    fact_id = uuid.uuid4().hex
                    await self.db.execute(
                        "INSERT INTO user_facts (id, fact, category, source, confidence, created_at, updated_at) "
                        "VALUES (?, ?, ?, 'extracted', 0.8, ?, ?)",
                        (fact_id, fact_text, category, now, now),
                    )
                    inserted += 1
                if inserted:
                    logger.info("Extracted %d new user facts from dreaming", inserted)
        except Exception:
            logger.debug("Dream user profile analysis failed", exc_info=True)

    async def _extract_experiences(self) -> None:
        """Analyze recent tool interactions and extract tactical lessons."""
        _EXPERIENCE_FALLBACK = (
            "Analyze recent tool interactions and extract tactical lessons. "
            "Respond with a JSON array of objects with: tool_name, situation, outcome, lesson, success, "
            "confidence (0-1), applicability (always|sometimes|rare)."
        )
        try:
            # Gather recent errors (last 24h) grouped by tool + error type
            error_rows = await self.db.fetch_all(
                "SELECT tool_name, error_type, COUNT(*) as count, "
                "GROUP_CONCAT(error_message, ' | ') as messages "
                "FROM tool_errors WHERE created_at > datetime('now', '-1 day') "
                "GROUP BY tool_name, error_type ORDER BY count DESC LIMIT 10"
            )
            errors_text = "None" if not error_rows else "\n".join(
                f"- {r['tool_name']} ({r['error_type']}): {r['count']}x -- {(r['messages'] or '')[:200]}"
                for r in error_rows
            )

            # Gather recent successes from query_log
            success_rows = await self.db.fetch_all(
                "SELECT tools_used, classification, AVG(evaluation_score) as avg_score, "
                "COUNT(*) as count "
                "FROM query_log WHERE evaluation_score > 0.7 "
                "AND created_at > datetime('now', '-1 day') "
                "AND tools_used IS NOT NULL "
                "GROUP BY tools_used ORDER BY avg_score DESC LIMIT 10"
            )
            successes_text = "None" if not success_rows else "\n".join(
                f"- {r['tools_used']} for {r['classification']}: {r['count']}x, avg score {(r['avg_score'] or 0):.1f}"
                for r in success_rows
            )

            if errors_text == "None" and successes_text == "None":
                return  # Nothing to analyze

            # Gather existing experiences to avoid duplication
            existing_rows = await self.db.fetch_all(
                "SELECT tool_name, lesson FROM agent_experiences "
                "ORDER BY updated_at DESC LIMIT 20"
            )
            existing_text = "None" if not existing_rows else "\n".join(
                f"- {r['tool_name']}: {r['lesson']}" for r in existing_rows
            )

            experiences = await run_prompt(
                self.provider,
                "experience_extraction.md",
                {
                    "errors": errors_text,
                    "successes": successes_text,
                    "existing": existing_text,
                },
                _EXPERIENCE_FALLBACK,
                model=self._background_model or None,
                max_tokens=600,
                temperature=0.3,
            )
            if not experiences or not isinstance(experiences, list):
                return

            now = datetime.now(timezone.utc).isoformat()
            inserted = 0
            for exp in experiences:
                if not isinstance(exp, dict) or not exp.get("lesson"):
                    continue
                tool_name = exp.get("tool_name", "unknown")
                situation = exp.get("situation", "")
                outcome = exp.get("outcome", "")
                lesson = exp.get("lesson", "")
                success = 1 if exp.get("success", True) else 0

                # Skip if a very similar lesson already exists
                existing = await self.db.fetch_one(
                    "SELECT id FROM agent_experiences WHERE lesson = ?",
                    (lesson,),
                )
                if existing:
                    continue

                confidence = exp.get("confidence", 0.8)
                if not isinstance(confidence, (int, float)) or confidence < 0 or confidence > 1:
                    confidence = 0.8
                applicability = exp.get("applicability", "sometimes")
                if applicability not in ("always", "sometimes", "rare"):
                    applicability = "sometimes"

                exp_id = uuid.uuid4().hex
                try:
                    await self.db.execute(
                        "INSERT INTO agent_experiences "
                        "(id, tool_name, situation, outcome, lesson, success, times_applied, "
                        "confidence, applicability, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)",
                        (exp_id, tool_name, situation, outcome, lesson, success,
                         confidence, applicability, now, now),
                    )
                except Exception:
                    # confidence/applicability columns may not exist yet
                    await self.db.execute(
                        "INSERT INTO agent_experiences "
                        "(id, tool_name, situation, outcome, lesson, success, times_applied, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)",
                        (exp_id, tool_name, situation, outcome, lesson, success, now, now),
                    )
                inserted += 1

            if inserted:
                logger.info("Extracted %d new tactical experiences", inserted)

        except Exception:
            logger.debug("Experience extraction failed", exc_info=True)

    async def _evaluate_plan_outcomes(self) -> None:
        """Evaluate completed plans to determine if they achieved their goals."""
        try:
            pending = await self.db.fetch_all(
                "SELECT po.plan_id, po.conversation_id "
                "FROM plan_outcomes po "
                "WHERE po.status = 'pending' "
                "LIMIT 3"
            )
            if not pending:
                return

            for row in pending:
                plan_id = row["plan_id"]
                conversation_id = row["conversation_id"]

                # Load the plan steps
                plan_row = await self.db.fetch_one(
                    "SELECT steps FROM task_plans WHERE id = ?", (plan_id,)
                )
                if not plan_row:
                    await self.db.execute(
                        "UPDATE plan_outcomes SET status = 'skipped', evaluated_at = datetime('now') "
                        "WHERE plan_id = ?",
                        (plan_id,),
                    )
                    continue

                steps = json.loads(plan_row["steps"])
                steps_text = "\n".join(
                    f"- Step {s['step']}: {s['task']} [{s.get('status', 'pending')}]"
                    + (f" -- {s['result']}" if s.get("result") else "")
                    for s in steps
                )

                # Load conversation excerpt
                msgs = await self.db.fetch_all(
                    "SELECT role, content FROM messages "
                    "WHERE conversation_id = ? ORDER BY timestamp DESC LIMIT 10",
                    (conversation_id,),
                )
                conversation_text = "\n".join(
                    f"{m['role']}: {(m['content'] or '')[:300]}" for m in reversed(msgs)
                ) if msgs else "(no conversation history)"

                result = await run_prompt(
                    self.provider,
                    "outcome_evaluation.md",
                    {"steps": steps_text, "conversation": conversation_text},
                    (
                        "Evaluate whether this task plan achieved its intended goal.\n\n"
                        "Plan steps:\n{steps}\n\nConversation excerpt:\n{conversation}\n\n"
                        'Respond ONLY with valid JSON: {{"score": 0.0-1.0, "achieved": true/false, "summary": "one sentence"}}'
                    ),
                    model=self._background_model or None,
                    max_tokens=200,
                    temperature=0.2,
                )

                now = datetime.now(timezone.utc).isoformat()
                if result:
                    await self.db.execute(
                        "UPDATE plan_outcomes SET status = 'evaluated', outcome_score = ?, "
                        "outcome_summary = ?, evaluated_at = ? WHERE plan_id = ?",
                        (result.get("score", 0.0), result.get("summary", ""), now, plan_id),
                    )
                    logger.info(
                        "Plan %s outcome: score=%.1f, %s",
                        plan_id[:8],
                        result.get("score", 0.0),
                        result.get("summary", "")[:80],
                    )
                else:
                    await self.db.execute(
                        "UPDATE plan_outcomes SET status = 'failed', evaluated_at = ? WHERE plan_id = ?",
                        (now, plan_id),
                    )
        except Exception:
            logger.debug("Plan outcome evaluation failed", exc_info=True)

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
