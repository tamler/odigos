from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from odigos.core.heartbeat import scheduled, todos, plans, peers, profiling, maintenance

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
    from odigos.db import Database

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
        evolution_engine: EvolutionEngine | None = None,
        strategist: Strategist | None = None,
        agent_client: AgentClient | None = None,
        agent_role: str = "",
        agent_description: str = "",
        announce_interval: int = 60,
        cron_manager: CronManager | None = None,
        notifier: Notifier | None = None,
        scheduler: Scheduler | None = None,
        ws_port: int = 8001,
        settings=None,
        budget_tracker=None,
        tool_registry=None,
        message_bus=None,
    ) -> None:
        self.db = db
        self.settings = settings
        self._budget_tracker = budget_tracker
        self.tool_registry = tool_registry
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
        self.message_bus = message_bus
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
        self._plan_fail_count: int = 0
        self._brain_lint_counter: int = 0
        self.current_phase: str | None = None
        self.current_activity: str | None = None
        self.current_plan: dict | None = None

    async def start(self) -> None:
        # On startup: recover orphaned sub-agent tasks
        try:
            from odigos.core.heartbeat import subagent_worker
            recovered = await subagent_worker.recover_orphaned_tasks(self)
            if recovered > 0:
                logger.info(
                    "Sub-agent worker: recovered %d orphaned tasks on startup", recovered
                )
        except Exception:
            logger.debug("Sub-agent orphan recovery failed", exc_info=True)

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

    def get_status(self) -> dict:
        """Return current heartbeat status for the activity dashboard."""
        return {
            "current_phase": self.current_phase,
            "current_activity": self.current_activity,
            "current_plan": self.current_plan,
        }

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

        # Budget gate: skip ALL LLM-touching phases when over budget
        _over_budget = False
        if hasattr(self, '_budget_tracker') and self._budget_tracker:
            try:
                status = await self._budget_tracker.check_budget()
                if not status.within_budget:
                    _over_budget = True
                    logger.warning("Heartbeat: over budget, skipping LLM phases")
            except Exception:
                pass

        # Idle gate: throttle LLM-heavy phases when no recent user activity.
        # Only briefing, scheduled tasks, reminders, and peer maintenance run
        # at full speed. Everything else (plans, proactive, evolution, profiling)
        # is suppressed until a user actually talks to the agent.
        _idle = False
        try:
            last_user_msg = await self.db.fetch_one(
                "SELECT created_at FROM messages WHERE role = 'user' AND channel = 'web' "
                "ORDER BY created_at DESC LIMIT 1"
            )
            if last_user_msg:
                from datetime import datetime, timezone
                last_ts = datetime.fromisoformat(
                    last_user_msg["created_at"].replace("Z", "+00:00")
                )
                if last_ts.tzinfo is None:
                    last_ts = last_ts.replace(tzinfo=timezone.utc)
                idle_minutes = (datetime.now(timezone.utc) - last_ts).total_seconds() / 60
                _idle = idle_minutes > 30
            else:
                _idle = True  # No user messages at all
        except Exception:
            pass

        did_work = False

        # Phase 0: Morning briefing (once per day)
        if not _over_budget:
            await scheduled.maybe_send_briefing(self)

        # Phase 1: Process scheduled tasks (unified reminders + cron)
        did_work |= await scheduled.process_scheduled_tasks(self)

        # Phase 1b: Fire legacy reminders (old table, for backward compat)
        did_work |= await scheduled.fire_reminders(self)

        # Phase 2: Work on pending todos (LLM calls — only when user is active)
        if not _over_budget and not _idle:
            did_work |= await todos.work_todos(self)

        # Phase 3: Deliver subagent results
        did_work |= await peers.deliver_subagent_results(self)

        # Phase 3b: Run legacy cron jobs (old table, for backward compat)
        did_work |= await maintenance.run_cron_jobs(self)

        # Phase 3c: Poll pending tasks — e.g. background_poll type (HTTP only, no LLM)
        from odigos.core.heartbeat import background
        did_work |= await background.poll_pending_tasks(self)

        # Phase 3d: Sub-agent task execution
        try:
            from odigos.core.heartbeat import subagent_worker
            started = await subagent_worker.poll_subagent_tasks(self)
            if started > 0:
                logger.info("Sub-agent worker: started %d tasks", started)
        except Exception:
            logger.debug("Sub-agent worker failed", exc_info=True)

        # Phase 3e: Wiki maintenance (drain pending writes, project entity pages)
        from odigos.core.heartbeat import brain_maintenance
        did_work |= await brain_maintenance.run_brain_maintenance(self)

        # Phase 3f: Brain compilation (sub-agent dispatch)
        try:
            from odigos.core.heartbeat import brain_compiler
            applied = await brain_compiler.check_compilation(self)
            if not applied and await brain_compiler.should_compile(self.db):
                await brain_compiler.dispatch_compilation(self)
        except Exception:
            logger.debug("Brain compiler phase failed", exc_info=True)

        # Wiki lint (every 10 ticks)
        self._brain_lint_counter += 1
        if self._brain_lint_counter >= 10:
            self._brain_lint_counter = 0
            await brain_maintenance.run_brain_lint(self)

        # Phase 4: Process inbound peer messages
        if self.agent_client:
            did_work |= await peers.process_peer_messages(self)

        # Phase 4b: Check email inbox (if configured, no LLM)
        _email_cfg = getattr(self, "_email_config", None)
        if _email_cfg and _email_cfg.enabled:
            if not hasattr(self, "_email_tick_counter"):
                self._email_tick_counter = 0
            self._email_tick_counter += 1
            interval = _email_cfg.check_interval_ticks or 10
            if self._email_tick_counter >= interval:
                self._email_tick_counter = 0
                did_work |= await maintenance.check_email(self)

        # Phase 4c: Proactive nudges (no LLM)
        #
        # Deliberately does NOT contribute to did_work -- see the note above the
        # gate at Phase 4e. Sending a nudge costs no LLM budget, so it must not
        # suppress the phases that the gate exists to ration.
        self._nudge_tick_counter += 1
        if self._nudge_tick_counter >= self._nudge_interval_ticks:
            self._nudge_tick_counter = 0
            await maintenance.send_nudges(self)

        # Phase 4d: Follow-up reminders (no LLM). Same: not did_work.
        self._followup_tick_counter += 1
        if self._followup_tick_counter >= self._followup_interval_ticks:
            self._followup_tick_counter = 0
            await maintenance.check_followups(self)

        # --- the did_work gate, and what it does and does not mean ------------
        #
        # Most phases from here down are gated `if not did_work`, so one unit of
        # work earlier in the tick suppresses plan execution, proactive,
        # evolution, dreaming, experience extraction, memory evolution and
        # outcome evaluation. On a busy agent those are the first things
        # skipped -- the headline features starve while the mechanical ones
        # always win. (Phase 9.6, notebook review, is gated only on _idle and
        # its own flag, not on this.)
        #
        # Kept, deliberately (charter §1 says decide and document, not invert).
        # The gate is a budget rationer: every phase below spends LLM tokens,
        # and firing them on top of a tick that already did real work is how you
        # get cost spikes. Inverting it would make expensive background work
        # pre-empt user-visible work, which is worse.
        #
        # Suppression defers rather than starves ONLY because the interval
        # counters now advance every tick, above. While they incremented inside
        # these blocks, a continuously busy agent never advanced them and the
        # interval-based phases could starve permanently.
        #
        # What was actually wrong is what fed the gate. did_work must mean
        # "this tick already spent LLM budget", not "something happened".
        # Phases 4c and 4d are labelled "no LLM" in their own comments and still
        # contributed, so a nudge could cancel evolution for that tick. They no
        # longer do.
        #
        # This mattered more than it looks: until the priority= fix, notify()
        # raised TypeError on every call, so send_nudges and check_followups
        # ALWAYS returned False and never tripped the gate. Repairing them would
        # have quietly started starving the LLM phases for the first time.
        #
        # Phases 3c and 4b are also marked "no LLM" but are left contributing:
        # they poll external HTTP and IMAP, which is real latency in the tick,
        # and changing them is not needed to fix the regression above.
        # ---------------------------------------------------------------------

        # Phase 4e: Proactive plan execution (LLM calls — only when user is active)
        if not did_work and not _over_budget and not _idle:
            did_work |= await plans.work_in_progress_plans(self)

        # Phase 5: Proactive pipeline (scan → prioritize → execute → publish)
        if not did_work and not _over_budget and not _idle:
            from odigos.core.heartbeat import proactive
            await proactive.run_proactive(self)

        # Phase 6: Self-improvement cycle (LLM calls — only when user is active)
        if not did_work and not _over_budget and not _idle and self.evolution_engine:
            await maintenance.run_evolution(self)

        # Phase 7: Peer announce + stale check
        if self.agent_client:
            await peers.peer_maintenance(self)

        # Interval counters advance every tick, NOT only on unsuppressed ones.
        # They previously incremented inside the `if not did_work` blocks, so a
        # continuously busy agent never advanced them and dreaming, experience
        # extraction and outcome evaluation could starve permanently rather than
        # merely being deferred. Elapsed time is not a function of whether the
        # tick was busy.
        self._dream_tick_counter += 1
        self._experience_tick_counter += 1
        self._outcome_tick_counter += 1

        # Phase 8: User profile dreaming (LLM calls — only when user is active)
        if not did_work and not _over_budget and not _idle:
            if self._dream_tick_counter >= self._dream_interval_ticks:
                self._dream_tick_counter = 0
                await profiling.dream_analyze_user(self)

        # Phase 9: Experience extraction (LLM calls — only when user is active)
        if not did_work and not _over_budget and not _idle:
            if self._experience_tick_counter >= self._experience_interval_ticks:
                self._experience_tick_counter = 0
                try:
                    self.current_phase = "experience_extraction"
                    self.current_activity = "Extracting agent experiences"
                    await profiling.extract_experiences(self)
                finally:
                    self.current_phase = None
                    self.current_activity = None

        # Phase 9.5: Memory evolution (refine + consolidate structured memories)
        if not did_work and not _over_budget and not _idle:
            if hasattr(self, "memory_evolution") and self.memory_evolution:
                try:
                    self.current_phase = "memory_evolution"
                    self.current_activity = "Refining memories"
                    stats = await self.memory_evolution.run_cycle()
                    if stats.get("processed", 0) > 0:
                        logger.info(
                            "Memory evolution: %d processed, %d consolidated",
                            stats["processed"],
                            stats.get("consolidated", 0),
                        )
                except Exception:
                    logger.debug("Memory evolution failed", exc_info=True)
                finally:
                    self.current_phase = None
                    self.current_activity = None

        # Phase 9.6: Notebook review (LLM calls — only when user is active)
        if getattr(self, "notes_review_enabled", False) and not _idle:
            try:
                self.current_phase = "notebook_review"
                self.current_activity = "Reviewing shared notebooks"
                from odigos.core.heartbeat import notes_review
                reviewed = await notes_review.review_notebooks(self)
                if reviewed > 0:
                    logger.info("Notebook review: %d notebook(s) reviewed", reviewed)
            except Exception:
                logger.debug("Notebook review phase failed", exc_info=True)
            finally:
                self.current_phase = None
                self.current_activity = None

        # Phase 10: Outcome evaluation (LLM calls — only when user is active)
        if not did_work and not _over_budget and not _idle:
            if self._outcome_tick_counter >= self._outcome_interval_ticks:
                self._outcome_tick_counter = 0
                await profiling.evaluate_plan_outcomes(self)

        # Phase 11: Auto-update check (if enabled)
        _update_cfg = self.settings.auto_update if self.settings else None
        if _update_cfg and _update_cfg.enabled:
            self._update_tick_counter += 1
            if self._update_tick_counter >= _update_cfg.check_interval_ticks:
                self._update_tick_counter = 0
                await maintenance.check_for_updates(self)

        # Phase 12: Storage quota check (every 60 ticks ~= 30min at 30s interval)
        self._quota_tick_counter += 1
        if self._quota_tick_counter >= 60:
            self._quota_tick_counter = 0
            await maintenance.check_storage_quota(self)

        if self.tracer:
            await self.tracer.emit("heartbeat_tick", None, {
                "did_work": did_work,
            })
