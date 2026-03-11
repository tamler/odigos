"""Test heartbeat announces agent to peers."""
import time
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_tick_announces_periodically():
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
    heartbeat.evolution_engine = None
    heartbeat.strategist = None
    heartbeat.agent_client = AsyncMock()
    heartbeat.agent_client.broadcast_announce = AsyncMock()
    heartbeat.agent_client.mark_stale_peers = AsyncMock(return_value=0)
    heartbeat._announce_interval = 60
    heartbeat._last_announce = time.monotonic() - 120  # ensure interval has elapsed
    heartbeat._agent_role = "personal_assistant"
    heartbeat._agent_description = "Test agent"

    heartbeat._fire_reminders = AsyncMock(return_value=False)
    heartbeat._work_todos = AsyncMock(return_value=False)
    heartbeat._deliver_subagent_results = AsyncMock(return_value=False)
    heartbeat._idle_think = AsyncMock()

    await heartbeat._tick()

    # Should have broadcast announce
    heartbeat.agent_client.broadcast_announce.assert_called_once()
    heartbeat.agent_client.mark_stale_peers.assert_called_once()
