"""Tests for CronExpression parsing.

The CronManager suite was removed with CronManager itself on 2026-08-12;
recurring tasks live in core/scheduler.py and are covered by its own tests.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from odigos.core.cron import CronExpression
from odigos.db import Database


# -- Fixtures --


@pytest_asyncio.fixture
async def db(tmp_db_path):
    d = Database(tmp_db_path, migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


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
