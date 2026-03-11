"""Test that heartbeat Phase 5 runs the strategist."""
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_tick_runs_strategist_when_should_run():
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
    heartbeat.evolution_engine.score_past_actions = AsyncMock(return_value=0)
    heartbeat.evolution_engine.check_active_trial = AsyncMock(return_value=None)
    heartbeat.strategist = AsyncMock()
    heartbeat.strategist.should_run = AsyncMock(return_value=True)
    heartbeat.strategist.analyze = AsyncMock(return_value={"hypotheses": []})

    heartbeat._fire_reminders = AsyncMock(return_value=False)
    heartbeat._work_todos = AsyncMock(return_value=False)
    heartbeat._deliver_subagent_results = AsyncMock(return_value=False)
    heartbeat._idle_think = AsyncMock()

    await heartbeat._tick()

    heartbeat.strategist.should_run.assert_called_once()
    heartbeat.strategist.analyze.assert_called_once()
