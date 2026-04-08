"""Tests for the proactive pipeline."""
from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from tests.conftest import FakeDB
from odigos.core.heartbeat.proactive import (
    Opportunity,
    prioritize,
    run_proactive,
    scan_brain_gaps,
)


@pytest_asyncio.fixture
async def proactive_db(fake_db: FakeDB) -> FakeDB:
    """Extend fake_db with entities and notifications tables."""
    await fake_db.execute("""
        CREATE TABLE IF NOT EXISTS entities (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            name TEXT NOT NULL,
            aliases_json TEXT,
            confidence REAL DEFAULT 1.0,
            status TEXT DEFAULT 'active',
            properties_json TEXT,
            summary TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(type, name)
        )
    """)
    await fake_db.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT,
            artifact_path TEXT,
            conversation_id TEXT,
            source TEXT,
            read INTEGER DEFAULT 0,
            reaction TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    return fake_db


def _make_hb(db, goal_store=None, proactive_config=None):
    """Build a minimal Heartbeat-like object for testing."""
    hb = SimpleNamespace(
        db=db,
        goal_store=goal_store,
        provider=None,
        notifier=None,
        agent=None,
        _last_idle=0.0,
        _background_model="",
    )
    if proactive_config is not None:
        hb._proactive_config = proactive_config
    return hb


@pytest.mark.asyncio
async def test_scan_brain_gaps(proactive_db: FakeDB):
    """Entities with no summary should produce opportunities."""
    await proactive_db.execute(
        "INSERT INTO entities (id, type, name, status) VALUES (?, ?, ?, ?)",
        ("e1", "person", "Alice", "active"),
    )
    hb = _make_hb(proactive_db)
    opps = await scan_brain_gaps(hb)
    assert len(opps) == 1
    assert opps[0].source == "brain_gaps"
    assert "Alice" in opps[0].title


@pytest.mark.asyncio
async def test_scan_returns_empty_when_no_gaps(proactive_db: FakeDB):
    """Entities with a summary should not produce opportunities."""
    await proactive_db.execute(
        "INSERT INTO entities (id, type, name, status, summary) VALUES (?, ?, ?, ?, ?)",
        ("e2", "person", "Bob", "active", "Bob is a developer."),
    )
    hb = _make_hb(proactive_db)
    opps = await scan_brain_gaps(hb)
    assert len(opps) == 0


@pytest.mark.asyncio
async def test_prioritize_filters_thumbs_down(proactive_db: FakeDB):
    """Sources with enough not_relevant reactions should be suppressed."""
    # Insert 3 thumbs-down notifications for brain_gaps
    for i in range(3):
        await proactive_db.execute(
            "INSERT INTO notifications (id, type, title, source, reaction) "
            "VALUES (?, ?, ?, ?, ?)",
            (f"n{i}", "finding", f"Test {i}", "brain_gaps", "not_relevant"),
        )

    hb = _make_hb(proactive_db)
    opps = [
        Opportunity(source="brain_gaps", title="Research X", context="no summary", priority_hint=0.9),
        Opportunity(source="active_goals", title="Goal Y", context="goal ctx", priority_hint=0.3),
    ]
    result = await prioritize(hb, opps)
    # brain_gaps should be filtered, leaving only active_goals
    assert result is not None
    assert result.source == "active_goals"


@pytest.mark.asyncio
async def test_prioritize_returns_highest_hint(proactive_db: FakeDB):
    """With <= 3 opportunities and no suppression, highest hint wins."""
    hb = _make_hb(proactive_db)
    opps = [
        Opportunity(source="a", title="Low", context="ctx", priority_hint=0.1),
        Opportunity(source="b", title="High", context="ctx", priority_hint=0.9),
        Opportunity(source="c", title="Mid", context="ctx", priority_hint=0.5),
    ]
    result = await prioritize(hb, opps)
    assert result is not None
    assert result.title == "High"


@pytest.mark.asyncio
async def test_run_proactive_skips_when_disabled(proactive_db: FakeDB):
    """When proactive config is disabled, run_proactive should return immediately."""
    config = SimpleNamespace(enabled=False, interval_seconds=900)
    hb = _make_hb(proactive_db, proactive_config=config)
    # Set _last_idle to 0 so rate limit wouldn't block
    hb._last_idle = 0.0

    await run_proactive(hb)

    # _last_idle should NOT have been updated since we returned early
    assert hb._last_idle == 0.0
