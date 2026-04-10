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
        background_model: str = "",
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

        did_work = False

        # Phase 0: Morning briefing (once per day)
        if not _over_budget:
            await scheduled.maybe_send_briefing(self)

        # Phase 1: Process scheduled tasks (unified reminders + cron)
        did_work |= await scheduled.process_scheduled_tasks(self)

        # Phase 1b: Fire legacy reminders (old table, for backward compat)
        did_work |= await scheduled.fire_reminders(self)

        # Phase 2: Work on pending todos (LLM calls)
        if not _over_budget:
            did_work |= await todos.work_todos(self)

        # Phase 3: Deliver subagent results
        did_work |= await peers.deliver_subagent_results(self)

        # Phase 3b: Run legacy cron jobs (old table, for backward compat)
        did_work |= await maintenance.run_cron_jobs(self)

        # Phase 3c: Poll pending tasks — e.g. background_poll type (HTTP only, no LLM)
        from odigos.core.heartbeat import background
        did_work |= await background.poll_pending_tasks(self)

        # Phase 3d: Wiki maintenance (drain pending writes, project entity pages)
        from odigos.core.heartbeat import brain_maintenance
        did_work |= await brain_maintenance.run_brain_maintenance(self)

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
        self._nudge_tick_counter += 1
        if self._nudge_tick_counter >= self._nudge_interval_ticks:
            self._nudge_tick_counter = 0
            did_work |= await maintenance.send_nudges(self)

        # Phase 4d: Follow-up reminders (no LLM)
        self._followup_tick_counter += 1
        if self._followup_tick_counter >= self._followup_interval_ticks:
            self._followup_tick_counter = 0
            did_work |= await maintenance.check_followups(self)

        # Phase 4e: Proactive plan execution (LLM calls)
        if not did_work and not _over_budget:
            did_work |= await plans.work_in_progress_plans(self)

        # Phase 5: Proactive pipeline (scan → prioritize → execute → publish)
        if not did_work and not _over_budget:
            from odigos.core.heartbeat import proactive
            await proactive.run_proactive(self)

        # Phase 6: Self-improvement cycle (LLM calls)
        if not did_work and not _over_budget and self.evolution_engine:
            await maintenance.run_evolution(self)

        # Phase 7: Peer announce + stale check
        if self.agent_client:
            await peers.peer_maintenance(self)

        # Phase 8: User profile dreaming (LLM calls, idle only)
        if not did_work and not _over_budget:
            self._dream_tick_counter += 1
            if self._dream_tick_counter >= self._dream_interval_ticks:
                self._dream_tick_counter = 0
                await profiling.dream_analyze_user(self)

        # Phase 9: Experience extraction (LLM calls, idle only)
        if not did_work and not _over_budget:
            self._experience_tick_counter += 1
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
        if not did_work and not _over_budget:
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

        # Phase 9.6: Notebook review
        if getattr(self, "notes_review_enabled", False):
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

        # Phase 10: Outcome evaluation (LLM calls, idle only)
        if not did_work and not _over_budget:
            self._outcome_tick_counter += 1
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
