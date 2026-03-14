"""Cron scheduler for periodic agent tasks."""
from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.db import Database

logger = logging.getLogger(__name__)


@dataclass
class CronEntry:
    """A scheduled cron job."""

    id: str
    name: str
    schedule: str
    action: str
    enabled: bool
    created_at: str
    last_run_at: str | None
    next_run_at: str | None
    conversation_id: str | None


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


class CronManager:
    """Manages cron entries stored in the database."""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def add(
        self,
        name: str,
        schedule: str,
        action: str,
        conversation_id: str | None = None,
    ) -> CronEntry:
        """Create a new cron entry after validating the schedule expression."""
        expr = CronExpression(schedule)  # raises ValueError if invalid
        now = datetime.now(timezone.utc)
        entry_id = str(uuid.uuid4())
        next_run = expr.next_from(now).isoformat()

        await self.db.execute(
            "INSERT INTO cron_entries (id, name, schedule, action, enabled, created_at, last_run_at, next_run_at, conversation_id) "
            "VALUES (?, ?, ?, ?, 1, ?, NULL, ?, ?)",
            (entry_id, name, schedule, action, now.isoformat(), next_run, conversation_id),
        )

        return CronEntry(
            id=entry_id,
            name=name,
            schedule=schedule,
            action=action,
            enabled=True,
            created_at=now.isoformat(),
            last_run_at=None,
            next_run_at=next_run,
            conversation_id=conversation_id,
        )

    async def remove(self, entry_id: str) -> None:
        """Delete a cron entry by ID."""
        await self.db.execute("DELETE FROM cron_entries WHERE id = ?", (entry_id,))

    async def list(self, enabled_only: bool = False) -> list[CronEntry]:
        """List cron entries, optionally filtering to enabled only."""
        if enabled_only:
            rows = await self.db.fetch_all(
                "SELECT * FROM cron_entries WHERE enabled = 1 ORDER BY created_at"
            )
        else:
            rows = await self.db.fetch_all(
                "SELECT * FROM cron_entries ORDER BY created_at"
            )
        return [self._row_to_entry(r) for r in rows]

    async def toggle(self, entry_id: str, enabled: bool) -> None:
        """Enable or disable a cron entry."""
        if enabled:
            # Recompute next_run_at when re-enabling
            row = await self.db.fetch_one(
                "SELECT schedule FROM cron_entries WHERE id = ?", (entry_id,)
            )
            if row:
                expr = CronExpression(row["schedule"])
                next_run = expr.next_from(datetime.now(timezone.utc)).isoformat()
                await self.db.execute(
                    "UPDATE cron_entries SET enabled = 1, next_run_at = ? WHERE id = ?",
                    (next_run, entry_id),
                )
            else:
                await self.db.execute(
                    "UPDATE cron_entries SET enabled = ? WHERE id = ?",
                    (1, entry_id),
                )
        else:
            await self.db.execute(
                "UPDATE cron_entries SET enabled = ? WHERE id = ?",
                (0, entry_id),
            )

    async def tick(self) -> list[CronEntry]:
        """Return entries that are due to run now.

        An entry is due if it is enabled and its next_run_at <= now.
        """
        now = datetime.now(timezone.utc).isoformat()
        rows = await self.db.fetch_all(
            "SELECT * FROM cron_entries WHERE enabled = 1 AND next_run_at <= ? "
            "ORDER BY next_run_at",
            (now,),
        )
        return [self._row_to_entry(r) for r in rows]

    async def mark_run(self, entry_id: str) -> None:
        """Update last_run_at and compute next_run_at after a cron entry has run."""
        now = datetime.now(timezone.utc)
        row = await self.db.fetch_one(
            "SELECT schedule FROM cron_entries WHERE id = ?", (entry_id,)
        )
        if not row:
            return
        expr = CronExpression(row["schedule"])
        next_run = expr.next_from(now).isoformat()
        await self.db.execute(
            "UPDATE cron_entries SET last_run_at = ?, next_run_at = ? WHERE id = ?",
            (now.isoformat(), next_run, entry_id),
        )

    @staticmethod
    def _row_to_entry(row: dict) -> CronEntry:
        return CronEntry(
            id=row["id"],
            name=row["name"],
            schedule=row["schedule"],
            action=row["action"],
            enabled=bool(row["enabled"]),
            created_at=row["created_at"],
            last_run_at=row.get("last_run_at"),
            next_run_at=row.get("next_run_at"),
            conversation_id=row.get("conversation_id"),
        )
