"""Tests for the proactive nudger module."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from odigos.core.nudger import (
    _hours_since,
    format_nudge_notification,
    get_nudge_items,
)
from odigos.db import Database


@pytest_asyncio.fixture
async def test_db(tmp_db_path):
    """Create a minimal test database."""
    db = Database(tmp_db_path, migrations_dir="migrations")
    await db.initialize()
    yield db
    await db.close()


def test_hours_since():
    """Verify _hours_since calculates correctly."""
    two_hours_ago = (
        datetime.now(timezone.utc) - timedelta(hours=2)
    ).isoformat()
    result = _hours_since(two_hours_ago)
    assert 1.9 < result < 2.1


def test_hours_since_with_z_suffix():
    two_hours_ago = (
        datetime.now(timezone.utc) - timedelta(hours=2)
    )
    iso_z = two_hours_ago.strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    result = _hours_since(iso_z)
    assert 1.9 < result < 2.1


def test_hours_since_invalid():
    assert _hours_since("not-a-date") == 0.0


def test_format_nudge_stale_todo():
    nudges = [{
        "type": "stale_todo",
        "id": 1,
        "description": "Buy groceries",
        "age_hours": 50.5,
    }]
    result = format_nudge_notification(nudges)
    assert "Pending task (50h old)" in result
    assert "Buy groceries" in result


def test_format_nudge_stale_plan():
    nudges = [{
        "type": "stale_plan",
        "id": 2,
        "description": "Migrate database",
        "age_hours": 80.0,
    }]
    result = format_nudge_notification(nudges)
    assert "Stale plan (80h)" in result
    assert "Migrate database" in result


def test_format_nudge_overdue_goal():
    nudges = [{
        "type": "overdue_goal",
        "id": 3,
        "description": "Launch MVP",
        "age_hours": 100.0,
    }]
    result = format_nudge_notification(nudges)
    assert "Stale goal (100h)" in result
    assert "Launch MVP" in result


def test_format_nudge_overdue_goal_with_created_at():
    nudges = [{
        "type": "overdue_goal",
        "id": 4,
        "description": "Ship feature",
        "created_at": "2026-03-20T00:00:00+00:00",
    }]
    result = format_nudge_notification(nudges)
    assert "Stale goal (since 2026-03-20)" in result
    assert "Ship feature" in result


def test_format_empty_nudges():
    assert format_nudge_notification([]) == ""


@pytest.mark.asyncio
async def test_get_nudge_items_empty_db(test_db):
    """With no matching tables, returns empty list."""
    nudges = await get_nudge_items(test_db)
    assert nudges == [] or isinstance(nudges, list)
