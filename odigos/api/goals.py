"""Goals, todos, and reminders API endpoints."""

from fastapi import APIRouter, Depends, Query

from odigos.api.deps import get_goal_store, require_auth
from odigos.core.goal_store import GoalStore

router = APIRouter(
    prefix="/api",
    dependencies=[Depends(require_auth)],
)


@router.get("/goals")
async def list_goals(
    status: str = Query(default="active"),
    store: GoalStore = Depends(get_goal_store),
):
    """List goals filtered by status."""
    goals = await store.list_goals(status=status)
    return {"goals": goals}


@router.get("/todos")
async def list_todos(
    status: str = Query(default="pending"),
    store: GoalStore = Depends(get_goal_store),
):
    """List todos filtered by status."""
    todos = await store.list_todos(status=status)
    return {"todos": todos}


@router.get("/reminders")
async def list_reminders(
    status: str = Query(default="pending"),
    store: GoalStore = Depends(get_goal_store),
):
    """List reminders filtered by status."""
    reminders = await store.list_reminders(status=status)
    return {"reminders": reminders}
