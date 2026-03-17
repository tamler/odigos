"""Evolution engine API endpoints for dashboard."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from odigos.api.deps import get_checkpoint_manager, get_db, require_auth
from odigos.db import Database

router = APIRouter(
    prefix="/api",
    dependencies=[Depends(require_auth)],
)


@router.get("/evolution/status")
async def get_evolution_status(db: Database = Depends(get_db)):
    """Get current evolution engine status."""
    active_trial = await db.fetch_one(
        "SELECT * FROM trials WHERE status = 'active' ORDER BY started_at DESC LIMIT 1"
    )
    eval_count = await db.fetch_one("SELECT COUNT(*) as cnt FROM evaluations")
    recent_evals = await db.fetch_all(
        "SELECT overall_score FROM evaluations ORDER BY created_at DESC LIMIT 20"
    )
    avg_score = None
    if recent_evals:
        scores = [r["overall_score"] for r in recent_evals if r["overall_score"] is not None]
        avg_score = sum(scores) / len(scores) if scores else None

    return {
        "active_trial": dict(active_trial) if active_trial else None,
        "recent_eval_count": eval_count["cnt"] if eval_count else 0,
        "recent_avg_score": avg_score,
    }


@router.get("/evolution/evaluations")
async def get_evaluations(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Database = Depends(get_db),
):
    """Get paginated evaluation history."""
    rows = await db.fetch_all(
        "SELECT * FROM evaluations ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    )
    return {"evaluations": [dict(r) for r in rows]}


@router.get("/evolution/directions")
async def get_directions(
    limit: int = Query(default=10, ge=1, le=50),
    db: Database = Depends(get_db),
):
    """Get direction log entries."""
    rows = await db.fetch_all(
        "SELECT * FROM direction_log ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )
    return {"directions": [dict(r) for r in rows]}


@router.get("/evolution/failed-trials")
async def get_failed_trials(
    limit: int = Query(default=20, ge=1, le=100),
    db: Database = Depends(get_db),
):
    """Get failed trial history."""
    rows = await db.fetch_all(
        "SELECT * FROM failed_trials_log ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )
    return {"failed_trials": [dict(r) for r in rows]}


@router.post("/evolution/trial/{trial_id}/promote")
async def promote_trial(
    trial_id: str,
    db: Database = Depends(get_db),
    checkpoint_mgr=Depends(get_checkpoint_manager),
):
    """Manually promote an active trial."""
    trial = await db.fetch_one(
        "SELECT * FROM trials WHERE id = ? AND status = 'active'", (trial_id,)
    )
    if not trial:
        raise HTTPException(status_code=404, detail="Active trial not found")
    await checkpoint_mgr.promote_trial(trial_id)
    return {"status": "promoted"}


@router.post("/evolution/trial/{trial_id}/revert")
async def revert_trial(
    trial_id: str,
    db: Database = Depends(get_db),
    checkpoint_mgr=Depends(get_checkpoint_manager),
):
    """Manually revert an active trial."""
    trial = await db.fetch_one(
        "SELECT * FROM trials WHERE id = ? AND status = 'active'", (trial_id,)
    )
    if not trial:
        raise HTTPException(status_code=404, detail="Active trial not found")
    await checkpoint_mgr.revert_trial(trial_id, reason="manual_revert")
    return {"status": "reverted"}


@router.get("/proposals")
async def get_proposals(
    status: str = Query(default="pending"),
    db: Database = Depends(get_db),
):
    """Get specialization proposals."""
    rows = await db.fetch_all(
        "SELECT * FROM specialization_proposals WHERE status = ? ORDER BY created_at DESC",
        (status,),
    )
    return {"proposals": [dict(r) for r in rows]}


@router.post("/proposals/{proposal_id}/approve")
async def approve_proposal(proposal_id: str, db: Database = Depends(get_db)):
    """Approve a specialization proposal."""
    row = await db.fetch_one(
        "SELECT * FROM specialization_proposals WHERE id = ? AND status = 'pending'",
        (proposal_id,),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Pending proposal not found")
    await db.execute(
        "UPDATE specialization_proposals SET status = 'approved', approved_at = datetime('now') "
        "WHERE id = ?",
        (proposal_id,),
    )
    return {"status": "approved"}


@router.post("/proposals/{proposal_id}/dismiss")
async def dismiss_proposal(proposal_id: str, db: Database = Depends(get_db)):
    """Dismiss a specialization proposal."""
    row = await db.fetch_one(
        "SELECT * FROM specialization_proposals WHERE id = ? AND status = 'pending'",
        (proposal_id,),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Pending proposal not found")
    await db.execute(
        "UPDATE specialization_proposals SET status = 'dismissed' WHERE id = ?",
        (proposal_id,),
    )
    return {"status": "dismissed"}
