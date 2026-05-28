from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field

from odigos.db import Database

logger = logging.getLogger(__name__)


@dataclass
class BudgetStatus:
    within_budget: bool
    warning: bool
    daily_spend: float          # LLM + tool spend combined
    monthly_spend: float        # LLM + tool spend combined
    daily_limit: float
    monthly_limit: float
    circuit_breaker: bool = False  # True when spend exceeds 90% of limit
    # Per-source breakdown for the Activity page; empty if no tool costs recorded.
    # Keys: 'llm', 'whisper', 'kie_image', 'kie_music', etc.
    by_source: dict = field(default_factory=dict)


class BudgetTracker:
    """Tracks LLM + paid-tool spending against daily/monthly caps."""

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
        """Total spend today across LLM (messages) + paid tools (tool_costs)."""
        llm_row = await self.db.fetch_one(
            "SELECT COALESCE(SUM(cost_usd), 0.0) AS total "
            "FROM messages WHERE date(created_at) = date('now')"
        )
        tool_row = await self.db.fetch_one(
            "SELECT COALESCE(SUM(cost_usd), 0.0) AS total "
            "FROM tool_costs WHERE date(created_at) = date('now')"
        )
        return (llm_row["total"] if llm_row else 0.0) + (tool_row["total"] if tool_row else 0.0)

    async def get_monthly_spend(self) -> float:
        """Total spend this month across LLM + paid tools."""
        llm_row = await self.db.fetch_one(
            "SELECT COALESCE(SUM(cost_usd), 0.0) AS total "
            "FROM messages WHERE strftime('%Y-%m', created_at) = strftime('%Y-%m', 'now')"
        )
        tool_row = await self.db.fetch_one(
            "SELECT COALESCE(SUM(cost_usd), 0.0) AS total "
            "FROM tool_costs WHERE strftime('%Y-%m', created_at) = strftime('%Y-%m', 'now')"
        )
        return (llm_row["total"] if llm_row else 0.0) + (tool_row["total"] if tool_row else 0.0)

    async def get_daily_breakdown(self) -> dict[str, float]:
        """Per-source spend today. 'llm' covers messages.cost_usd; rest from tool_costs.source."""
        out: dict[str, float] = {}
        llm_row = await self.db.fetch_one(
            "SELECT COALESCE(SUM(cost_usd), 0.0) AS total "
            "FROM messages WHERE date(created_at) = date('now')"
        )
        llm_total = llm_row["total"] if llm_row else 0.0
        if llm_total > 0:
            out["llm"] = llm_total
        rows = await self.db.fetch_all(
            "SELECT source, COALESCE(SUM(cost_usd), 0.0) AS total "
            "FROM tool_costs WHERE date(created_at) = date('now') "
            "GROUP BY source"
        )
        for r in rows or []:
            if r["total"] > 0:
                out[r["source"]] = r["total"]
        return out

    async def record_tool_cost(
        self,
        cost_usd: float,
        *,
        source: str,
        conversation_id: str | None = None,
        tool_name: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        """Record a successful paid-tool call so it aggregates into the budget cap.

        Only call on the success path — failures should not be billed (matches LLM behavior).
        `source` is the provider (e.g. 'whisper', 'kie_image', 'kie_music'); `tool_name` is
        the Odigos tool that invoked it (e.g. 'voice_stt', 'generate_image').
        """
        if cost_usd <= 0:
            return
        await self.db.execute(
            "INSERT INTO tool_costs (id, conversation_id, source, tool_name, cost_usd, metadata_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                uuid.uuid4().hex,
                conversation_id,
                source,
                tool_name,
                float(cost_usd),
                json.dumps(metadata) if metadata else None,
            ),
        )

    async def check_budget(self, extra_cost: float = 0.0) -> BudgetStatus:
        daily = await self.get_daily_spend() + extra_cost
        monthly = await self.get_monthly_spend() + extra_cost

        over_daily = self.daily_limit > 0 and daily >= self.daily_limit
        over_monthly = self.monthly_limit > 0 and monthly >= self.monthly_limit
        within = not over_daily and not over_monthly

        warn_daily = self.daily_limit > 0 and daily >= self.daily_limit * self.warn_threshold
        warn_monthly = self.monthly_limit > 0 and monthly >= self.monthly_limit * self.warn_threshold
        warning = (warn_daily or warn_monthly) and within

        if not within:
            logger.warning(
                "Budget EXCEEDED: daily=$%.4f/$%.2f, monthly=$%.4f/$%.2f",
                daily, self.daily_limit, monthly, self.monthly_limit,
            )
        elif warning:
            logger.warning(
                "Budget warning (>%.0f%%): daily=$%.4f/$%.2f, monthly=$%.4f/$%.2f",
                self.warn_threshold * 100,
                daily, self.daily_limit, monthly, self.monthly_limit,
            )

        # Circuit breaker trips at 90% of limit — forces fallback model + reduced tool turns
        near_daily = self.daily_limit > 0 and daily >= self.daily_limit * 0.9
        near_monthly = self.monthly_limit > 0 and monthly >= self.monthly_limit * 0.9
        circuit_breaker = near_daily or near_monthly

        if circuit_breaker and within:
            logger.info(
                "Budget circuit breaker: >90%% of limit, switching to degraded mode"
            )

        by_source = await self.get_daily_breakdown()

        return BudgetStatus(
            within_budget=within,
            warning=warning,
            daily_spend=daily,
            monthly_spend=monthly,
            daily_limit=self.daily_limit,
            monthly_limit=self.monthly_limit,
            circuit_breaker=circuit_breaker,
            by_source=by_source,
        )
