"""System metrics API endpoint."""

from fastapi import APIRouter, Depends

from odigos.api.deps import get_db, require_auth
from odigos.db import Database

router = APIRouter(
    prefix="/api",
    dependencies=[Depends(require_auth)],
)


@router.get("/metrics")
async def get_metrics(
    db: Database = Depends(get_db),
):
    """Return aggregate system metrics."""
    conv_row = await db.fetch_one("SELECT COUNT(*) AS cnt FROM conversations")
    msg_row = await db.fetch_one(
        "SELECT COUNT(*) AS cnt, COALESCE(SUM(cost_usd), 0.0) AS total_cost FROM messages"
    )
    return {
        "conversation_count": conv_row["cnt"] if conv_row else 0,
        "message_count": msg_row["cnt"] if msg_row else 0,
        "total_cost_usd": msg_row["total_cost"] if msg_row else 0.0,
    }
