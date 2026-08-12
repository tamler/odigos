"""Test heartbeat peer maintenance phase."""
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from odigos.core.heartbeat import Heartbeat


def _build_heartbeat(**overrides):
    """Build a Heartbeat with all fields set, overridable for testing."""
    hb = Heartbeat.__new__(Heartbeat)
    hb.db = overrides.get("db", AsyncMock())
    hb.agent = AsyncMock()
    hb.channel_registry = MagicMock()
    hb.goal_store = AsyncMock()
    hb.provider = AsyncMock()
    hb._interval = 30
    hb._max_todos_per_tick = 3
    hb._idle_think_interval = 900
    hb._task = None
    hb.tracer = None
    hb.subagent_manager = None
    hb._last_idle = 0
    hb.paused = False
    hb.evolution_engine = None
    hb.strategist = None
    hb.agent_client = overrides.get("agent_client", None)
    hb._announce_interval = 60
    hb._last_announce = time.monotonic() - 120
    hb._agent_role = "personal_assistant"
    hb._agent_description = "Test agent"
    hb._ws_port = 8001
    hb.scheduler = None
    hb.cron_manager = None
    hb.notifier = None
    hb._dream_tick_counter = 0
    hb._dream_interval_ticks = 10
    hb._experience_tick_counter = 0
    hb._experience_interval_ticks = 20
    hb._outcome_tick_counter = 0
    hb._outcome_interval_ticks = 10
    hb._nudge_tick_counter = 0
    hb._nudge_interval_ticks = 20
    hb._followup_tick_counter = 0
    hb._followup_interval_ticks = 30
    hb._update_tick_counter = 0
    hb._email_tick_counter = 0
    hb.settings = None
    hb._budget_tracker = None
    hb._quota_tick_counter = 0
    hb._email_config = None
    hb._background_model = ""
    hb._plan_fail_count = 0
    hb._brain_lint_counter = 0
    hb.current_phase = None
    hb.current_activity = None
    hb.current_plan = None
    hb.tool_registry = None
    hb.message_bus = None
    return hb


def _tick_patches():
    """Combined context manager to patch all heartbeat phases except peer maintenance."""
    import contextlib
    return contextlib.ExitStack()


def _enter_tick_patches(stack):
    """Enter all patches into an ExitStack."""
    targets = [
        ("odigos.core.heartbeat.scheduled.maybe_send_briefing", {}),
        ("odigos.core.heartbeat.scheduled.process_scheduled_tasks", {"return_value": False}),
        ("odigos.core.heartbeat.scheduled.fire_reminders", {"return_value": False}),
        ("odigos.core.heartbeat.todos.work_todos", {"return_value": False}),
        ("odigos.core.heartbeat.peers.deliver_subagent_results", {"return_value": False}),
        ("odigos.core.heartbeat.maintenance.send_nudges", {"return_value": False}),
        ("odigos.core.heartbeat.maintenance.check_followups", {"return_value": False}),
        ("odigos.core.heartbeat.plans.work_in_progress_plans", {"return_value": False}),
        ("odigos.core.heartbeat.background.poll_pending_tasks", {"return_value": False}),
        ("odigos.core.heartbeat.brain_maintenance.run_brain_maintenance", {"return_value": False}),
        ("odigos.core.heartbeat.brain_maintenance.run_brain_lint", {}),
        ("odigos.core.heartbeat.proactive.run_proactive", {}),
        ("odigos.core.heartbeat.maintenance.run_evolution", {}),
        ("odigos.core.heartbeat.profiling.dream_analyze_user", {}),
        ("odigos.core.heartbeat.profiling.extract_experiences", {}),
        ("odigos.core.heartbeat.profiling.evaluate_plan_outcomes", {}),
        ("odigos.core.heartbeat.maintenance.check_storage_quota", {}),
    ]
    for target, kwargs in targets:
        stack.enter_context(patch(target, new_callable=AsyncMock, **kwargs))


@pytest.mark.asyncio
async def test_tick_announces_and_flushes():
    agent_client = AsyncMock()
    agent_client.broadcast_announce = AsyncMock()
    agent_client.mark_stale_peers = AsyncMock(return_value=0)
    agent_client.flush_outbox = AsyncMock(return_value=0)
    agent_client.list_peer_names = MagicMock(return_value=["Archie"])

    hb = _build_heartbeat(agent_client=agent_client)
    import contextlib
    with contextlib.ExitStack() as stack:
        _enter_tick_patches(stack)
        await hb._tick()

    agent_client.broadcast_announce.assert_called_once()
    agent_client.mark_stale_peers.assert_called_once()
    agent_client.flush_outbox.assert_called_once()


@pytest.mark.asyncio
async def test_tick_inert_when_no_peers():
    """Peer maintenance is skipped entirely when no peers exist."""
    agent_client = AsyncMock()
    agent_client.list_peer_names = MagicMock(return_value=[])
    agent_client.broadcast_announce = AsyncMock()
    agent_client.flush_outbox = AsyncMock()

    db = AsyncMock()
    db.fetch_one = AsyncMock(return_value=None)  # No online peers in registry

    hb = _build_heartbeat(agent_client=agent_client, db=db)
    import contextlib
    with contextlib.ExitStack() as stack:
        _enter_tick_patches(stack)
        await hb._tick()

    agent_client.broadcast_announce.assert_not_called()
    agent_client.flush_outbox.assert_not_called()


@pytest.mark.asyncio
async def test_tick_skips_peer_when_no_agent_client():
    """No crash when agent_client is None."""
    hb = _build_heartbeat(agent_client=None)
    import contextlib
    with contextlib.ExitStack() as stack:
        _enter_tick_patches(stack)
        await hb._tick()
    # Should complete without error
