"""Test heartbeat peer maintenance phase."""
import time
from unittest.mock import AsyncMock, MagicMock

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

    hb.cron_manager = None
    hb.notifier = None
    hb._ws_port = 8001
    hb._dream_tick_counter = 0
    hb._dream_interval_ticks = 10
    hb._experience_tick_counter = 0
    hb._experience_interval_ticks = 20
    hb._outcome_tick_counter = 0
    hb._outcome_interval_ticks = 10
    hb._fire_reminders = AsyncMock(return_value=False)
    hb._work_todos = AsyncMock(return_value=False)
    hb._deliver_subagent_results = AsyncMock(return_value=False)
    hb._idle_think = AsyncMock()
    hb._background_model = ""
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
    await hb._tick()
    # Should complete without error
