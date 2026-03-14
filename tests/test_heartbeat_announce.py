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
    hb._fire_reminders = AsyncMock(return_value=False)
    hb._work_todos = AsyncMock(return_value=False)
    hb._deliver_subagent_results = AsyncMock(return_value=False)
    hb._idle_think = AsyncMock()
    return hb


@pytest.mark.asyncio
async def test_tick_announces_and_flushes():
    agent_client = AsyncMock()
    agent_client.broadcast_announce = AsyncMock()
    agent_client.mark_stale_peers = AsyncMock(return_value=0)
    agent_client.flush_outbox = AsyncMock(return_value=0)
    agent_client.list_peer_names = MagicMock(return_value=["Archie"])

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

    db = AsyncMock()
    db.fetch_one = AsyncMock(return_value=None)  # No online peers in registry

    hb = _build_heartbeat(agent_client=agent_client, db=db)
    await hb._tick()

    agent_client.broadcast_announce.assert_not_called()
    agent_client.flush_outbox.assert_not_called()


@pytest.mark.asyncio
async def test_tick_skips_peer_when_no_agent_client():
    """No crash when agent_client is None."""
    hb = _build_heartbeat(agent_client=None)
    await hb._tick()
    # Should complete without error
