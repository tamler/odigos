import uuid

import pytest

from odigos.core.budget import BudgetTracker
from odigos.db import Database


@pytest.fixture
async def db(tmp_db_path: str) -> Database:
    database = Database(tmp_db_path, migrations_dir="migrations")
    await database.initialize()
    yield database
    await database.close()


async def _insert_message(db: Database, cost: float, conv_id: str = "conv-1") -> None:
    """Insert a message with a specific cost for budget testing."""
    existing = await db.fetch_one("SELECT id FROM conversations WHERE id = ?", (conv_id,))
    if not existing:
        await db.execute(
            "INSERT INTO conversations (id, channel) VALUES (?, ?)",
            (conv_id, "test"),
        )
    await db.execute(
        "INSERT INTO messages (id, conversation_id, role, content, cost_usd) "
        "VALUES (?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), conv_id, "assistant", "test", cost),
    )


class TestBudgetTracker:
    async def test_daily_spend_empty(self, db: Database):
        tracker = BudgetTracker(db=db)
        spend = await tracker.get_daily_spend()
        assert spend == 0.0

    async def test_daily_spend_sums_today(self, db: Database):
        tracker = BudgetTracker(db=db)
        await _insert_message(db, 0.01)
        await _insert_message(db, 0.02)
        spend = await tracker.get_daily_spend()
        assert abs(spend - 0.03) < 1e-9

    async def test_monthly_spend_sums(self, db: Database):
        tracker = BudgetTracker(db=db)
        await _insert_message(db, 0.05)
        await _insert_message(db, 0.10)
        spend = await tracker.get_monthly_spend()
        assert abs(spend - 0.15) < 1e-9

    async def test_check_budget_within(self, db: Database):
        tracker = BudgetTracker(db=db, daily_limit=1.00, monthly_limit=20.00)
        status = await tracker.check_budget()
        assert status.within_budget is True
        assert status.daily_spend == 0.0

    async def test_check_budget_warns_at_80_pct(self, db: Database):
        tracker = BudgetTracker(db=db, daily_limit=0.10, monthly_limit=20.00)
        await _insert_message(db, 0.09)  # 90% of daily
        status = await tracker.check_budget()
        assert status.within_budget is False

    async def test_check_budget_monthly_warn(self, db: Database):
        tracker = BudgetTracker(db=db, daily_limit=100.00, monthly_limit=0.10)
        await _insert_message(db, 0.09)  # 90% of monthly
        status = await tracker.check_budget()
        assert status.within_budget is False
