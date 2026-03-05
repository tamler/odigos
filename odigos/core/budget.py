from __future__ import annotations

import logging
from dataclasses import dataclass

from odigos.db import Database

logger = logging.getLogger(__name__)


@dataclass
class BudgetStatus:
    within_budget: bool
    daily_spend: float
    monthly_spend: float
    daily_limit: float
    monthly_limit: float


class BudgetTracker:
    """Tracks LLM spending by querying stored message costs."""

    def __init__(
        self,
        db: Database,
        daily_limit: float = 1.00,
        monthly_limit: float = 20.00,
        warn_threshold: float = 0.80,
    ) -> None:
        self.db = db
        self.daily_limit = daily_limit
        self.monthly_limit = monthly_limit
        self.warn_threshold = warn_threshold

    async def get_daily_spend(self) -> float:
        row = await self.db.fetch_one(
            "SELECT COALESCE(SUM(cost_usd), 0.0) AS total "
            "FROM messages WHERE date(timestamp) = date('now')"
        )
        return row["total"] if row else 0.0

    async def get_monthly_spend(self) -> float:
        row = await self.db.fetch_one(
            "SELECT COALESCE(SUM(cost_usd), 0.0) AS total "
            "FROM messages WHERE strftime('%Y-%m', timestamp) = strftime('%Y-%m', 'now')"
        )
        return row["total"] if row else 0.0

    async def check_budget(self) -> BudgetStatus:
        daily = await self.get_daily_spend()
        monthly = await self.get_monthly_spend()

        within = (
            daily < self.daily_limit * self.warn_threshold
            and monthly < self.monthly_limit * self.warn_threshold
        )

        if not within:
            logger.warning(
                "Budget warning: daily=$%.4f/%s (%.0f%%), monthly=$%.4f/%s (%.0f%%)",
                daily,
                self.daily_limit,
                (daily / self.daily_limit * 100) if self.daily_limit else 0,
                monthly,
                self.monthly_limit,
                (monthly / self.monthly_limit * 100) if self.monthly_limit else 0,
            )

        return BudgetStatus(
            within_budget=within,
            daily_spend=daily,
            monthly_spend=monthly,
            daily_limit=self.daily_limit,
            monthly_limit=self.monthly_limit,
        )
