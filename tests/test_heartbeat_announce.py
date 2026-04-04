"""Test heartbeat peer maintenance phase."""
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from odigos.core.heartbeat import Heartbeat

# Common patches for all tick-level module calls
_MODULE_PATCHES = [
    ("odigos.core.heartbeat.scheduled.maybe_send_briefing", AsyncMock),
    ("odigos.core.heartbeat.scheduled.process_scheduled_tasks", AsyncMock),
    ("odigos.core.heartbeat.scheduled.fire_reminders", AsyncMock),
    ("odigos.core.heartbeat.todos.work_todos", AsyncMock),
    ("odigos.core.heartbeat.peers.deliver_subagent_results", AsyncMock),
    ("odigos.core.heartbeat.maintenance.run_cron_jobs", AsyncMock),
    ("odigos.core.heartbeat.maintenance.send_nudges", AsyncMock),
    ("odigos.core.heartbeat.maintenance.check_followups", AsyncMock),
    ("odigos.core.heartbeat.plans.work_in_progress_plans", AsyncMock),
    ("odigos.core.heartbeat.idle.idle_think", AsyncMock),
    ("odigos.core.heartbeat.maintenance.run_evolution", AsyncMock),
    ("odigos.core.heartbeat.profiling.dream_analyze_user", AsyncMock),
    ("odigos.core.heartbeat.profiling.extract_experiences", AsyncMock),
    ("odigos.core.heartbeat.profiling.evaluate_plan_outcomes", AsyncMock),
    ("odigos.core.heartbeat.maintenance.check_storage_quota", AsyncMock),
]


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

    hb.cron_manager = None
    hb.notifier = None
    hb.scheduler = None
    hb._ws_port = 8001
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
    hb._background_model = ""
    hb._budget_tracker = None
    hb._quota_tick_counter = 0
    hb._email_config = None
    hb._plan_fail_count = 0
    return hb


@pytest.mark.asyncio
async def test_tick_announces_and_flushes():
    agent_client = AsyncMock()
    agent_client.broadcast_announce = AsyncMock()
    agent_client.mark_stale_peers = AsyncMock(return_value=0)
    agent_client.flush_outbox = AsyncMock(return_value=0)
    agent_client.list_peer_names = MagicMock(return_value=["Archie"])
    agent_client.get_unprocessed_inbound = AsyncMock(return_value=[])

    hb = _build_heartbeat(agent_client=agent_client)

    # Patch all module calls except peers (which we want to exercise)
    patches = [patch(target, new_callable=cls, return_value=False) for target, cls in _MODULE_PATCHES]
    # Also need to NOT patch peers.peer_maintenance and peers.process_peer_messages
    with patch("odigos.core.heartbeat.scheduled.maybe_send_briefing", new_callable=AsyncMock), \
         patch("odigos.core.heartbeat.scheduled.process_scheduled_tasks", new_callable=AsyncMock, return_value=False), \
         patch("odigos.core.heartbeat.scheduled.fire_reminders", new_callable=AsyncMock, return_value=False), \
         patch("odigos.core.heartbeat.todos.work_todos", new_callable=AsyncMock, return_value=False), \
         patch("odigos.core.heartbeat.peers.deliver_subagent_results", new_callable=AsyncMock, return_value=False), \
         patch("odigos.core.heartbeat.maintenance.run_cron_jobs", new_callable=AsyncMock, return_value=False), \
         patch("odigos.core.heartbeat.maintenance.send_nudges", new_callable=AsyncMock, return_value=False), \
         patch("odigos.core.heartbeat.maintenance.check_followups", new_callable=AsyncMock, return_value=False), \
         patch("odigos.core.heartbeat.plans.work_in_progress_plans", new_callable=AsyncMock, return_value=False), \
         patch("odigos.core.heartbeat.idle.idle_think", new_callable=AsyncMock), \
         patch("odigos.core.heartbeat.maintenance.run_evolution", new_callable=AsyncMock), \
         patch("odigos.core.heartbeat.profiling.dream_analyze_user", new_callable=AsyncMock), \
         patch("odigos.core.heartbeat.profiling.extract_experiences", new_callable=AsyncMock), \
         patch("odigos.core.heartbeat.profiling.evaluate_plan_outcomes", new_callable=AsyncMock), \
         patch("odigos.core.heartbeat.maintenance.check_storage_quota", new_callable=AsyncMock):
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
    agent_client.get_unprocessed_inbound = AsyncMock(return_value=[])

    db = AsyncMock()
    db.fetch_one = AsyncMock(return_value=None)  # No online peers in registry

    hb = _build_heartbeat(agent_client=agent_client, db=db)

    with patch("odigos.core.heartbeat.scheduled.maybe_send_briefing", new_callable=AsyncMock), \
         patch("odigos.core.heartbeat.scheduled.process_scheduled_tasks", new_callable=AsyncMock, return_value=False), \
         patch("odigos.core.heartbeat.scheduled.fire_reminders", new_callable=AsyncMock, return_value=False), \
         patch("odigos.core.heartbeat.todos.work_todos", new_callable=AsyncMock, return_value=False), \
         patch("odigos.core.heartbeat.peers.deliver_subagent_results", new_callable=AsyncMock, return_value=False), \
         patch("odigos.core.heartbeat.maintenance.run_cron_jobs", new_callable=AsyncMock, return_value=False), \
         patch("odigos.core.heartbeat.maintenance.send_nudges", new_callable=AsyncMock, return_value=False), \
         patch("odigos.core.heartbeat.maintenance.check_followups", new_callable=AsyncMock, return_value=False), \
         patch("odigos.core.heartbeat.plans.work_in_progress_plans", new_callable=AsyncMock, return_value=False), \
         patch("odigos.core.heartbeat.idle.idle_think", new_callable=AsyncMock), \
         patch("odigos.core.heartbeat.maintenance.run_evolution", new_callable=AsyncMock), \
         patch("odigos.core.heartbeat.profiling.dream_analyze_user", new_callable=AsyncMock), \
         patch("odigos.core.heartbeat.profiling.extract_experiences", new_callable=AsyncMock), \
         patch("odigos.core.heartbeat.profiling.evaluate_plan_outcomes", new_callable=AsyncMock), \
         patch("odigos.core.heartbeat.maintenance.check_storage_quota", new_callable=AsyncMock):
        await hb._tick()

    agent_client.broadcast_announce.assert_not_called()
    agent_client.flush_outbox.assert_not_called()


@pytest.mark.asyncio
async def test_tick_processes_inbound_messages():
    """Heartbeat processes unhandled inbound peer messages."""
    agent_client = AsyncMock()
    agent_client.list_peer_names = MagicMock(return_value=["Archie"])
    agent_client.broadcast_announce = AsyncMock()
    agent_client.mark_stale_peers = AsyncMock(return_value=0)
    agent_client.flush_outbox = AsyncMock(return_value=0)
    agent_client.get_unprocessed_inbound = AsyncMock(return_value=[
        {
            "message_id": "msg-1",
            "peer_name": "Archie",
            "message_type": "message",
            "content": '{"content": "Server disk is at 95%"}',
            "created_at": "2026-03-14T00:00:00",
            "response_to": None,
        }
    ])
    agent_client.mark_processed = AsyncMock()
    agent_client.send = AsyncMock(return_value={"status": "delivered"})

    hb = _build_heartbeat(agent_client=agent_client)
    hb.agent = AsyncMock()
    hb.agent.handle_message = AsyncMock(return_value="I'll look into the disk usage.")

    with patch("odigos.core.heartbeat.scheduled.maybe_send_briefing", new_callable=AsyncMock), \
         patch("odigos.core.heartbeat.scheduled.process_scheduled_tasks", new_callable=AsyncMock, return_value=False), \
         patch("odigos.core.heartbeat.scheduled.fire_reminders", new_callable=AsyncMock, return_value=False), \
         patch("odigos.core.heartbeat.todos.work_todos", new_callable=AsyncMock, return_value=False), \
         patch("odigos.core.heartbeat.peers.deliver_subagent_results", new_callable=AsyncMock, return_value=False), \
         patch("odigos.core.heartbeat.maintenance.run_cron_jobs", new_callable=AsyncMock, return_value=False), \
         patch("odigos.core.heartbeat.maintenance.send_nudges", new_callable=AsyncMock, return_value=False), \
         patch("odigos.core.heartbeat.maintenance.check_followups", new_callable=AsyncMock, return_value=False), \
         patch("odigos.core.heartbeat.plans.work_in_progress_plans", new_callable=AsyncMock, return_value=False), \
         patch("odigos.core.heartbeat.idle.idle_think", new_callable=AsyncMock), \
         patch("odigos.core.heartbeat.maintenance.run_evolution", new_callable=AsyncMock), \
         patch("odigos.core.heartbeat.profiling.dream_analyze_user", new_callable=AsyncMock), \
         patch("odigos.core.heartbeat.profiling.extract_experiences", new_callable=AsyncMock), \
         patch("odigos.core.heartbeat.profiling.evaluate_plan_outcomes", new_callable=AsyncMock), \
         patch("odigos.core.heartbeat.maintenance.check_storage_quota", new_callable=AsyncMock):
        await hb._tick()

    # Agent should have been called with a UniversalMessage containing the peer message
    hb.agent.handle_message.assert_called_once()
    msg_arg = hb.agent.handle_message.call_args[0][0]
    assert "Archie" in msg_arg.content
    assert "Server disk is at 95%" in msg_arg.content

    # Message should be marked processed
    agent_client.mark_processed.assert_called_once_with("msg-1")

    # Response should be sent back to the peer
    agent_client.send.assert_called()


@pytest.mark.asyncio
async def test_tick_skips_peer_when_no_agent_client():
    """No crash when agent_client is None."""
    hb = _build_heartbeat(agent_client=None)

    with patch("odigos.core.heartbeat.scheduled.maybe_send_briefing", new_callable=AsyncMock), \
         patch("odigos.core.heartbeat.scheduled.process_scheduled_tasks", new_callable=AsyncMock, return_value=False), \
         patch("odigos.core.heartbeat.scheduled.fire_reminders", new_callable=AsyncMock, return_value=False), \
         patch("odigos.core.heartbeat.todos.work_todos", new_callable=AsyncMock, return_value=False), \
         patch("odigos.core.heartbeat.peers.deliver_subagent_results", new_callable=AsyncMock, return_value=False), \
         patch("odigos.core.heartbeat.maintenance.run_cron_jobs", new_callable=AsyncMock, return_value=False), \
         patch("odigos.core.heartbeat.maintenance.send_nudges", new_callable=AsyncMock, return_value=False), \
         patch("odigos.core.heartbeat.maintenance.check_followups", new_callable=AsyncMock, return_value=False), \
         patch("odigos.core.heartbeat.plans.work_in_progress_plans", new_callable=AsyncMock, return_value=False), \
         patch("odigos.core.heartbeat.idle.idle_think", new_callable=AsyncMock), \
         patch("odigos.core.heartbeat.maintenance.run_evolution", new_callable=AsyncMock), \
         patch("odigos.core.heartbeat.profiling.dream_analyze_user", new_callable=AsyncMock), \
         patch("odigos.core.heartbeat.profiling.extract_experiences", new_callable=AsyncMock), \
         patch("odigos.core.heartbeat.profiling.evaluate_plan_outcomes", new_callable=AsyncMock), \
         patch("odigos.core.heartbeat.maintenance.check_storage_quota", new_callable=AsyncMock):
        await hb._tick()
    # Should complete without error
