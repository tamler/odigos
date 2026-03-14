"""Tests for cron scheduler — CronManager and CronExpression."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from odigos.core.cron import CronEntry, CronExpression, CronManager
from odigos.db import Database


# -- Fixtures --


@pytest_asyncio.fixture
async def db(tmp_db_path):
    d = Database(tmp_db_path, migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


@pytest_asyncio.fixture
async def cron_manager(db):
    return CronManager(db=db)


# -- CronExpression parsing tests --


class TestCronExpression:
    def test_every_minute(self):
        expr = CronExpression("* * * * *")
        now = datetime(2026, 3, 14, 10, 30, tzinfo=timezone.utc)
        assert expr.matches(now)

    def test_specific_minute(self):
        expr = CronExpression("30 * * * *")
        assert expr.matches(datetime(2026, 3, 14, 10, 30, tzinfo=timezone.utc))
        assert not expr.matches(datetime(2026, 3, 14, 10, 31, tzinfo=timezone.utc))

    def test_every_5_minutes(self):
        expr = CronExpression("*/5 * * * *")
        assert expr.matches(datetime(2026, 3, 14, 10, 0, tzinfo=timezone.utc))
        assert expr.matches(datetime(2026, 3, 14, 10, 5, tzinfo=timezone.utc))
        assert expr.matches(datetime(2026, 3, 14, 10, 55, tzinfo=timezone.utc))
        assert not expr.matches(datetime(2026, 3, 14, 10, 3, tzinfo=timezone.utc))

    def test_daily_at_9am(self):
        expr = CronExpression("0 9 * * *")
        assert expr.matches(datetime(2026, 3, 14, 9, 0, tzinfo=timezone.utc))
        assert not expr.matches(datetime(2026, 3, 14, 10, 0, tzinfo=timezone.utc))
        assert not expr.matches(datetime(2026, 3, 14, 9, 1, tzinfo=timezone.utc))

    def test_weekday_only(self):
        # Monday=1 through Friday=5 in cron (Sunday=0)
        expr = CronExpression("0 9 * * 1-5")
        # 2026-03-14 is a Saturday (cron dow=6)
        assert not expr.matches(datetime(2026, 3, 14, 9, 0, tzinfo=timezone.utc))
        # 2026-03-16 is a Monday (cron dow=1)
        assert expr.matches(datetime(2026, 3, 16, 9, 0, tzinfo=timezone.utc))

    def test_specific_days(self):
        expr = CronExpression("0 12 1,15 * *")
        assert expr.matches(datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc))
        assert expr.matches(datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc))
        assert not expr.matches(datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc))

    def test_range_field(self):
        expr = CronExpression("0-5 * * * *")
        assert expr.matches(datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc))
        assert expr.matches(datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc))
        assert not expr.matches(datetime(2026, 1, 1, 0, 6, tzinfo=timezone.utc))

    def test_invalid_field_count(self):
        with pytest.raises(ValueError, match="5 fields"):
            CronExpression("* * *")

    def test_invalid_value(self):
        with pytest.raises(ValueError):
            CronExpression("60 * * * *")

    def test_invalid_step_zero(self):
        with pytest.raises(ValueError, match="Step value cannot be 0"):
            CronExpression("*/0 * * * *")

    def test_invalid_range(self):
        with pytest.raises(ValueError):
            CronExpression("5-2 * * * *")

    def test_validate_good(self):
        assert CronExpression.validate("*/5 * * * *")

    def test_validate_bad(self):
        assert not CronExpression.validate("bad expression")

    def test_next_from(self):
        expr = CronExpression("30 10 * * *")
        base = datetime(2026, 3, 14, 9, 0, tzinfo=timezone.utc)
        nxt = expr.next_from(base)
        assert nxt == datetime(2026, 3, 14, 10, 30, tzinfo=timezone.utc)

    def test_next_from_wraps_day(self):
        expr = CronExpression("0 8 * * *")
        base = datetime(2026, 3, 14, 9, 0, tzinfo=timezone.utc)
        nxt = expr.next_from(base)
        assert nxt == datetime(2026, 3, 15, 8, 0, tzinfo=timezone.utc)

    def test_next_from_every_5(self):
        expr = CronExpression("*/5 * * * *")
        base = datetime(2026, 3, 14, 10, 2, tzinfo=timezone.utc)
        nxt = expr.next_from(base)
        assert nxt == datetime(2026, 3, 14, 10, 5, tzinfo=timezone.utc)


# -- CronManager tests --


class TestCronManager:
    @pytest.mark.asyncio
    async def test_add_and_list(self, cron_manager):
        entry = await cron_manager.add(
            name="Test Job",
            schedule="*/5 * * * *",
            action="Check the weather",
        )
        assert isinstance(entry, CronEntry)
        assert entry.name == "Test Job"
        assert entry.schedule == "*/5 * * * *"
        assert entry.action == "Check the weather"
        assert entry.enabled is True
        assert entry.next_run_at is not None

        entries = await cron_manager.list()
        assert len(entries) == 1
        assert entries[0].id == entry.id

    @pytest.mark.asyncio
    async def test_add_invalid_schedule(self, cron_manager):
        with pytest.raises(ValueError):
            await cron_manager.add(
                name="Bad Job",
                schedule="not a cron expr",
                action="something",
            )

    @pytest.mark.asyncio
    async def test_remove(self, cron_manager):
        entry = await cron_manager.add(
            name="To Remove",
            schedule="* * * * *",
            action="test",
        )
        await cron_manager.remove(entry.id)
        entries = await cron_manager.list()
        assert len(entries) == 0

    @pytest.mark.asyncio
    async def test_toggle(self, cron_manager):
        entry = await cron_manager.add(
            name="Toggle Test",
            schedule="0 9 * * *",
            action="test",
        )
        assert entry.enabled is True

        await cron_manager.toggle(entry.id, False)
        entries = await cron_manager.list()
        assert entries[0].enabled is False

        await cron_manager.toggle(entry.id, True)
        entries = await cron_manager.list()
        assert entries[0].enabled is True

    @pytest.mark.asyncio
    async def test_list_enabled_only(self, cron_manager):
        await cron_manager.add(name="Enabled", schedule="* * * * *", action="a")
        entry2 = await cron_manager.add(name="Disabled", schedule="* * * * *", action="b")
        await cron_manager.toggle(entry2.id, False)

        all_entries = await cron_manager.list(enabled_only=False)
        assert len(all_entries) == 2

        enabled_entries = await cron_manager.list(enabled_only=True)
        assert len(enabled_entries) == 1
        assert enabled_entries[0].name == "Enabled"

    @pytest.mark.asyncio
    async def test_tick_returns_due_entries(self, cron_manager, db):
        # Create an entry that should be due (next_run_at in the past)
        entry = await cron_manager.add(
            name="Due Job",
            schedule="* * * * *",
            action="do something",
        )
        # Force next_run_at to the past
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        await db.execute(
            "UPDATE cron_entries SET next_run_at = ? WHERE id = ?",
            (past, entry.id),
        )

        due = await cron_manager.tick()
        assert len(due) == 1
        assert due[0].id == entry.id

    @pytest.mark.asyncio
    async def test_tick_skips_future_entries(self, cron_manager, db):
        entry = await cron_manager.add(
            name="Future Job",
            schedule="0 0 1 1 *",  # Jan 1 midnight
            action="new year task",
        )
        # next_run_at is already in the future (next Jan 1)
        due = await cron_manager.tick()
        assert len(due) == 0

    @pytest.mark.asyncio
    async def test_tick_skips_disabled_entries(self, cron_manager, db):
        entry = await cron_manager.add(
            name="Disabled Due",
            schedule="* * * * *",
            action="test",
        )
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        await db.execute(
            "UPDATE cron_entries SET next_run_at = ? WHERE id = ?",
            (past, entry.id),
        )
        await cron_manager.toggle(entry.id, False)

        due = await cron_manager.tick()
        assert len(due) == 0

    @pytest.mark.asyncio
    async def test_mark_run_updates_timestamps(self, cron_manager, db):
        entry = await cron_manager.add(
            name="Run Test",
            schedule="*/5 * * * *",
            action="test",
        )

        # Force next_run_at to the past so mark_run produces a different next_run_at
        past = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        await db.execute(
            "UPDATE cron_entries SET next_run_at = ? WHERE id = ?",
            (past, entry.id),
        )

        await cron_manager.mark_run(entry.id)

        entries = await cron_manager.list()
        updated = entries[0]
        assert updated.last_run_at is not None
        assert updated.next_run_at is not None
        # next_run_at should now be in the future (after mark_run recomputes it)
        assert updated.next_run_at > updated.last_run_at

    @pytest.mark.asyncio
    async def test_add_with_conversation_id(self, cron_manager):
        entry = await cron_manager.add(
            name="Conv Job",
            schedule="0 9 * * *",
            action="daily report",
            conversation_id="web:abc123",
        )
        assert entry.conversation_id == "web:abc123"
        entries = await cron_manager.list()
        assert entries[0].conversation_id == "web:abc123"
