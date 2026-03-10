"""Tests for budget status API endpoint."""

from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from odigos.api.budget import router
from odigos.core.budget import BudgetStatus


def _make_app(budget_tracker) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.budget_tracker = budget_tracker
    app.state.settings = type("S", (), {"api_key": ""})()
    return app


@pytest.mark.asyncio
async def test_get_budget_status():
    status = BudgetStatus(
        within_budget=True,
        warning=False,
        daily_spend=0.42,
        monthly_spend=5.10,
        daily_limit=1.00,
        monthly_limit=20.00,
    )
    tracker = AsyncMock()
    tracker.check_budget = AsyncMock(return_value=status)

    app = _make_app(tracker)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/budget")

    assert resp.status_code == 200
    data = resp.json()
    assert data == asdict(status)
    tracker.check_budget.assert_awaited_once()
