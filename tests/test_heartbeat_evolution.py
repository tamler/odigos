"""Test that heartbeat Phase 5 runs the evolution cycle."""
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_tick_runs_evolution_when_idle():
    """Phase 5 should run when no other work was done."""
    from odigos.core.heartbeat import Heartbeat

    heartbeat = Heartbeat.__new__(Heartbeat)
    heartbeat.db = AsyncMock()
    heartbeat.agent = AsyncMock()
    heartbeat.channel_registry = MagicMock()
    heartbeat.goal_store = AsyncMock()
    heartbeat.provider = AsyncMock()
    heartbeat._interval = 30
    heartbeat._max_todos_per_tick = 3
    heartbeat._idle_think_interval = 900
    heartbeat._task = None
    heartbeat.tracer = None
    heartbeat.subagent_manager = None
    heartbeat._last_idle = 0
    heartbeat.paused = False
    heartbeat.evolution_engine = AsyncMock()
    heartbeat.evolution_engine.score_past_actions = AsyncMock(return_value=2)
    heartbeat.evolution_engine.check_active_trial = AsyncMock(return_value=None)

    heartbeat.agent_client = None
    heartbeat.cron_manager = None
    heartbeat.notifier = None
    heartbeat.scheduler = None
    heartbeat._dream_tick_counter = 0
    heartbeat._dream_interval_ticks = 10
    heartbeat._experience_tick_counter = 0
    heartbeat._experience_interval_ticks = 20
    heartbeat._outcome_tick_counter = 0
    heartbeat._outcome_interval_ticks = 10
    heartbeat._nudge_tick_counter = 0
    heartbeat._nudge_interval_ticks = 20
    heartbeat._followup_tick_counter = 0
    heartbeat._followup_interval_ticks = 30
    heartbeat._update_tick_counter = 0
    heartbeat._email_tick_counter = 0
    heartbeat.settings = None

    heartbeat._fire_reminders = AsyncMock(return_value=False)
    heartbeat._work_todos = AsyncMock(return_value=False)
    heartbeat._deliver_subagent_results = AsyncMock(return_value=False)
    heartbeat._idle_think = AsyncMock()
    heartbeat._budget_tracker = None
    heartbeat._quota_tick_counter = 0
    heartbeat._email_config = None
    heartbeat._background_model = ""
    heartbeat._maybe_send_briefing = AsyncMock()
    heartbeat._process_scheduled_tasks = AsyncMock(return_value=False)
    heartbeat._run_cron_jobs = AsyncMock(return_value=False)
    heartbeat._send_nudges = AsyncMock(return_value=False)
    heartbeat._check_followups = AsyncMock(return_value=False)
    heartbeat._work_in_progress_plans = AsyncMock(return_value=False)
    heartbeat._peer_maintenance = AsyncMock()
    heartbeat._dream_analyze_user = AsyncMock()
    heartbeat._extract_experiences = AsyncMock()
    heartbeat._evaluate_plan_outcomes = AsyncMock()
    heartbeat._check_storage_quota = AsyncMock()

    await heartbeat._tick()

    heartbeat.evolution_engine.score_past_actions.assert_called_once()
    heartbeat.evolution_engine.check_active_trial.assert_called_once()
