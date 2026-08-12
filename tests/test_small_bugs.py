"""Charter 01-cleanup.md §1, the smaller bugs.

Every one is the same shape: a lookup that silently returns a default instead of
failing, so the feature reads as working. Two used getattr with a fallback, one
used isinstance to coerce None to 0, one ordered a write behind a call that
always raised.
"""
import tempfile
from pathlib import Path

import pytest

from odigos.config import AgentConfig
from odigos.db import Database


@pytest.fixture
async def db():
    with tempfile.TemporaryDirectory() as d:
        database = Database(str(Path(d) / "t.db"), migrations_dir="migrations")
        await database.initialize()
        yield database
        await database.close()


async def test_execute_returning_rowcount_reports_affected_rows(db):
    await db.execute(
        "INSERT INTO agent_registry (agent_name, status, last_seen) "
        "VALUES (?, 'online', datetime('now', '-60 minutes'))",
        ("peer-a",),
    )
    await db.execute(
        "INSERT INTO agent_registry (agent_name, status, last_seen) "
        "VALUES (?, 'online', datetime('now', '-60 minutes'))",
        ("peer-b",),
    )
    n = await db.execute_returning_rowcount(
        "UPDATE agent_registry SET status = 'offline' WHERE status = 'online'"
    )
    assert n == 2
    assert await db.execute_returning_rowcount(
        "UPDATE agent_registry SET status = 'offline' WHERE status = 'online'"
    ) == 0


async def test_mark_stale_peers_returns_a_real_count(db):
    """It returned 0 unconditionally: db.execute() returns None, and the old
    `isinstance(result, int)` guard turned that into 0."""
    from odigos.core.agent_client import AgentClient

    await db.execute(
        "INSERT INTO agent_registry (agent_name, status, last_seen) "
        "VALUES (?, 'online', datetime('now', '-60 minutes'))",
        ("stale-peer",),
    )

    client = AgentClient.__new__(AgentClient)
    client._db = db

    assert await client.mark_stale_peers(stale_minutes=5) == 1, (
        "mark_stale_peers still reports 0 while marking rows offline"
    )
    row = await db.fetch_one(
        "SELECT status FROM agent_registry WHERE agent_name = ?", ("stale-peer",)
    )
    assert row["status"] == "offline"


async def test_cron_manager_has_no_entries_attribute(db):
    """api/state.py read `cron_manager.entries` via getattr with a [] default."""
    from odigos.core.cron import CronManager

    manager = CronManager(db=db)
    assert not hasattr(manager, "entries"), (
        "if CronManager grows an `entries` attribute, revisit api/state.py"
    )
    assert await manager.list() == []


async def test_cron_state_counts_real_entries(db):
    from odigos.core.cron import CronManager

    manager = CronManager(db=db)
    await manager.add(name="nightly", schedule="0 3 * * *", action="do a thing")
    entries = await manager.list()
    assert len(entries) == 1, "api/state.py would have reported 0 here"


def test_history_limit_is_a_real_config_field():
    """context.py read settings.agent.history_limit; AgentConfig never had it,
    so the knob was permanently pinned to the getattr fallback of 20."""
    assert AgentConfig().history_limit == 20
    assert AgentConfig(history_limit=50).history_limit == 50


async def test_storage_quota_is_recorded_even_when_notify_fails(db):
    """The kv write sat after the notify calls inside one try, so a notify
    failure skipped it -- exactly when usage was at or over the threshold."""
    from types import SimpleNamespace

    from odigos.core.heartbeat import maintenance

    class _ExplodingNotifier:
        async def notify(self, **kwargs):
            raise RuntimeError("notify is broken")

    hb = SimpleNamespace(
        db=db,
        notifier=_ExplodingNotifier(),
        settings=SimpleNamespace(storage=SimpleNamespace(warn_gb=0.0, cap_gb=0.0)),
    )

    await maintenance.check_storage_quota(hb)

    row = await db.fetch_one("SELECT value FROM kv WHERE key = 'storage_usage_gb'")
    assert row is not None, (
        "storage usage was not recorded because notify raised first"
    )
    assert float(row["value"]) >= 0.0
