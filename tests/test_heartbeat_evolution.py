"""Test that heartbeat Phase 6 runs the evolution cycle."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_tick_runs_evolution_when_idle():
    """Phase 6 should run when no other work was done."""
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
    heartbeat._budget_tracker = None
    heartbeat._quota_tick_counter = 0
    heartbeat._email_config = None
    heartbeat._background_model = ""
    heartbeat.strategist = None
    heartbeat._plan_fail_count = 0

    with (
        patch("odigos.core.heartbeat.scheduled.maybe_send_briefing", new_callable=AsyncMock),
        patch(
            "odigos.core.heartbeat.scheduled.process_scheduled_tasks",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "odigos.core.heartbeat.scheduled.fire_reminders",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "odigos.core.heartbeat.todos.work_todos",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "odigos.core.heartbeat.peers.deliver_subagent_results",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "odigos.core.heartbeat.maintenance.run_cron_jobs",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "odigos.core.heartbeat.maintenance.send_nudges",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "odigos.core.heartbeat.maintenance.check_followups",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "odigos.core.heartbeat.plans.work_in_progress_plans",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch("odigos.core.heartbeat.idle.idle_think", new_callable=AsyncMock),
        patch("odigos.core.heartbeat.maintenance.run_evolution", new_callable=AsyncMock)
            as mock_evolution,
        patch("odigos.core.heartbeat.profiling.dream_analyze_user", new_callable=AsyncMock),
        patch("odigos.core.heartbeat.profiling.extract_experiences", new_callable=AsyncMock),
        patch("odigos.core.heartbeat.profiling.evaluate_plan_outcomes", new_callable=AsyncMock),
        patch("odigos.core.heartbeat.maintenance.check_storage_quota", new_callable=AsyncMock),
    ):
        await heartbeat._tick()

        mock_evolution.assert_called_once_with(heartbeat)
