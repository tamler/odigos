"""Tests for heartbeat plan execution and stale-step recovery."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from odigos.core.heartbeat.plans import _reset_stale_in_progress_steps


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ago_iso(minutes: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


class TestStaleStepReset:
    def test_resets_stale_in_progress_step(self):
        """Step in_progress for >30 minutes is reset to pending."""
        steps = [
            {"step": 1, "task": "Step one", "status": "done"},
            {"step": 2, "task": "Step two", "status": "in_progress"},
            {"step": 3, "task": "Step three", "status": "pending"},
        ]
        result = _reset_stale_in_progress_steps(steps, _ago_iso(45))
        assert result is True
        assert steps[1]["status"] == "pending"
        assert steps[0]["status"] == "done"  # Done steps untouched
        assert steps[2]["status"] == "pending"  # Pending steps untouched

    def test_does_not_reset_recent_in_progress_step(self):
        """Step in_progress for <30 minutes is NOT reset."""
        steps = [
            {"step": 1, "task": "Step one", "status": "in_progress"},
            {"step": 2, "task": "Step two", "status": "pending"},
        ]
        result = _reset_stale_in_progress_steps(steps, _ago_iso(5))
        assert result is False
        assert steps[0]["status"] == "in_progress"

    def test_resets_substeps_when_stale(self):
        """Substeps in_progress past threshold are also reset."""
        steps = [
            {
                "step": 1,
                "task": "Parent",
                "status": "in_progress",
                "substeps": [
                    {"step": "1a", "task": "Sub one", "status": "done"},
                    {"step": "1b", "task": "Sub two", "status": "in_progress"},
                ],
            },
        ]
        result = _reset_stale_in_progress_steps(steps, _ago_iso(60))
        assert result is True
        assert steps[0]["status"] == "pending"
        assert steps[0]["substeps"][1]["status"] == "pending"
        assert steps[0]["substeps"][0]["status"] == "done"

    def test_no_stuck_steps_returns_false(self):
        """No in_progress steps means nothing to reset."""
        steps = [
            {"step": 1, "status": "done"},
            {"step": 2, "status": "pending"},
        ]
        result = _reset_stale_in_progress_steps(steps, _ago_iso(60))
        assert result is False

    def test_handles_invalid_timestamp(self):
        """Invalid updated_at returns False without raising."""
        steps = [{"step": 1, "status": "in_progress"}]
        result = _reset_stale_in_progress_steps(steps, "not-a-date")
        assert result is False
        assert steps[0]["status"] == "in_progress"

    def test_handles_z_suffix_timestamp(self):
        """ISO timestamps with Z suffix are parsed correctly."""
        steps = [{"step": 1, "status": "in_progress"}]
        old_time = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat().replace("+00:00", "Z")
        result = _reset_stale_in_progress_steps(steps, old_time)
        assert result is True
        assert steps[0]["status"] == "pending"
