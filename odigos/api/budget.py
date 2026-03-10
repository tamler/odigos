"""Budget status API endpoint."""

from dataclasses import asdict

from fastapi import APIRouter, Depends

from odigos.api.deps import get_budget_tracker, require_api_key
from odigos.core.budget import BudgetTracker

router = APIRouter(
    prefix="/api",
    dependencies=[Depends(require_api_key)],
)


@router.get("/budget")
async def get_budget_status(
    budget_tracker: BudgetTracker = Depends(get_budget_tracker),
):
    """Return current budget status including spend and limits."""
    status = await budget_tracker.check_budget()
    return asdict(status)
