"""Tests for Heartbeat.get_status() method."""
from __future__ import annotations

from unittest.mock import MagicMock

from odigos.core.heartbeat.orchestrator import Heartbeat


class TestHeartbeatStatus:
    def test_get_status_returns_idle_by_default(self):
        # Create a minimal Heartbeat without running it
        hb = MagicMock(spec=Heartbeat)
        # Use the real method bound to the mock
        hb.current_phase = None
        hb.current_activity = None
        hb.current_plan = None
        hb.get_status = Heartbeat.get_status.__get__(hb, Heartbeat)

        status = hb.get_status()
        assert status["current_phase"] is None
        assert status["current_activity"] is None
        assert status["current_plan"] is None

    def test_get_status_returns_active_phase(self):
        hb = MagicMock(spec=Heartbeat)
        hb.current_phase = "memory_evolution"
        hb.current_activity = "Processing 5 evolution queue items"
        hb.current_plan = None
        hb.get_status = Heartbeat.get_status.__get__(hb, Heartbeat)

        status = hb.get_status()
        assert status["current_phase"] == "memory_evolution"
        assert status["current_activity"] == "Processing 5 evolution queue items"

    def test_get_status_returns_active_plan(self):
        hb = MagicMock(spec=Heartbeat)
        hb.current_phase = "plans"
        hb.current_activity = None
        hb.current_plan = {
            "id": "abc-123",
            "goal": "Draft newsletter",
            "current_step": 3,
            "total_steps": 5,
        }
        hb.get_status = Heartbeat.get_status.__get__(hb, Heartbeat)

        status = hb.get_status()
        assert status["current_plan"]["goal"] == "Draft newsletter"
        assert status["current_plan"]["current_step"] == 3
