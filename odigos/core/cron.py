"""Cron expression parsing.

CronManager and CronEntry lived here until 2026-08-12. They managed a legacy
`cron_entries` table that the unified Scheduler (core/scheduler.py, backed by
`scheduled_tasks`) superseded -- api/cron.py already served every user-facing
cron route from the Scheduler, so CronManager had no production caller left
except a heartbeat phase replaying rows nothing could create.

CronExpression stays: core/scheduler.py:9 imports it, and it is what parses the
schedules the Scheduler stores.
"""
from __future__ import annotations

import re
from datetime import datetime


class CronExpression:
    """Simple cron expression parser.

    Supports standard 5-field cron expressions (minute hour day-of-month month day-of-week).
    Field syntax:
      * — every value
      N — at exactly N
      */N — every N intervals
      N,M — at N and M
      N-M — range from N to M (inclusive)
    """

    def __init__(self, expression: str) -> None:
        self.expression = expression
        self._fields = self._parse(expression)

    @staticmethod
    def validate(expression: str) -> bool:
        """Return True if the expression is a valid cron expression."""
        try:
            CronExpression(expression)
            return True
        except ValueError:
            return False

    def _parse(self, expression: str) -> list[set[int]]:
        parts = expression.strip().split()
        if len(parts) != 5:
            raise ValueError(
                f"Cron expression must have 5 fields (minute hour dom month dow), got {len(parts)}: {expression!r}"
            )

        ranges = [
            (0, 59),   # minute
            (0, 23),   # hour
            (1, 31),   # day of month
            (1, 12),   # month
            (0, 6),    # day of week (0=Sunday)
        ]

        fields = []
        for part, (lo, hi) in zip(parts, ranges):
            fields.append(self._parse_field(part, lo, hi))
        return fields

    def _parse_field(self, field_str: str, lo: int, hi: int) -> set[int]:
        """Parse a single cron field into a set of valid values."""
        result: set[int] = set()
        for token in field_str.split(","):
            token = token.strip()
            # */N
            step_match = re.match(r"^\*/(\d+)$", token)
            if step_match:
                step = int(step_match.group(1))
                if step == 0:
                    raise ValueError(f"Step value cannot be 0 in {field_str!r}")
                result.update(range(lo, hi + 1, step))
                continue

            # * (wildcard)
            if token == "*":
                result.update(range(lo, hi + 1))
                continue

            # N-M
            range_match = re.match(r"^(\d+)-(\d+)$", token)
            if range_match:
                start, end = int(range_match.group(1)), int(range_match.group(2))
                if start < lo or end > hi or start > end:
                    raise ValueError(f"Range {start}-{end} out of bounds ({lo}-{hi})")
                result.update(range(start, end + 1))
                continue

            # N (exact)
            if re.match(r"^\d+$", token):
                val = int(token)
                if val < lo or val > hi:
                    raise ValueError(f"Value {val} out of bounds ({lo}-{hi})")
                result.add(val)
                continue

            raise ValueError(f"Invalid cron field token: {token!r}")

        return result

    def matches(self, dt: datetime) -> bool:
        """Check if a datetime matches this cron expression."""
        minute, hour, dom, month, dow = self._fields
        # Convert Python weekday (Monday=0) to cron weekday (Sunday=0)
        cron_dow = (dt.weekday() + 1) % 7
        return (
            dt.minute in minute
            and dt.hour in hour
            and dt.day in dom
            and dt.month in month
            and cron_dow in dow
        )

    def next_from(self, dt: datetime) -> datetime:
        """Find the next datetime after dt that matches this expression.

        Searches minute-by-minute up to ~2 years ahead.
        """
        from datetime import timedelta

        # Start from the next minute
        candidate = dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
        max_iterations = 60 * 24 * 366 * 2  # ~2 years of minutes
        for _ in range(max_iterations):
            if self.matches(candidate):
                return candidate
            candidate += timedelta(minutes=1)
        raise ValueError(f"No matching time found within 2 years for expression: {self.expression}")
