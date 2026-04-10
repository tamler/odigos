"""Heartbeat Phase 3d: poll pending sub-agent tasks and delegate execution.

This worker is a thin scheduler. It:
1. Checks budget
2. Enforces per-pool concurrency limits
3. Marks pending tasks as running
4. Hands each task to SubagentManager.execute_task() in a background coroutine
5. Recovers orphaned tasks on startup

All execution logic (LLM dispatch, scoped tools, chaining, notifications)
lives in SubagentManager, which this worker delegates to.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Concurrency pools — tasks with the same concurrency_key share a slot pool
CONCURRENCY_POOLS: dict[str, int] = {
    "default": 3,
    "research": 2,
    "fast": 5,
    "heavy": 1,
}

SUBAGENT_POLL_LIMIT = 5  # max pending tasks checked per heartbeat cycle
ORPHAN_GRACE_SECONDS = 60

# Module-level task registry for cancellation
_running_tasks: dict[str, asyncio.Task] = {}


async def poll_subagent_tasks(hb) -> int:
    """Phase 3d: poll and start pending sub-agent tasks.

    Returns the number of tasks started in this cycle. Delegates actual
    execution to hb.subagent_manager.execute_task().
    """
    if not getattr(hb, "subagent_manager", None):
        return 0

    # Budget gating
    try:
        within_budget = await hb.budget_tracker.is_within_budget()
        if not within_budget:
            logger.debug("Sub-agent worker: budget exceeded, skipping")
            return 0
    except Exception:
        logger.debug("Budget check failed, assuming within budget", exc_info=True)

    # Get running task counts per concurrency pool
    running_rows = await hb.db.fetch_all(
        "SELECT concurrency_key, COUNT(*) as c FROM tasks "
        "WHERE type = 'subagent' AND status = 'running' "
        "GROUP BY concurrency_key",
    )
    running_counts: dict[str, int] = {
        (r["concurrency_key"] or "default"): r["c"] for r in running_rows
    }

    # Fetch pending tasks
    pending = await hb.db.fetch_all(
        "SELECT * FROM tasks WHERE type = 'subagent' AND status = 'pending' "
        "AND cancel_requested = 0 ORDER BY created_at ASC LIMIT ?",
        (SUBAGENT_POLL_LIMIT,),
    )

    if not pending:
        return 0

    started = 0
    for task_row in pending:
        key = task_row["concurrency_key"] or "default"
        limit = CONCURRENCY_POOLS.get(key, 3)
        current = running_counts.get(key, 0)
        if current >= limit:
            continue

        # Mark as running
        await hb.db.execute(
            "UPDATE tasks SET status = 'running', started_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), task_row["id"]),
        )
        running_counts[key] = current + 1

        # Launch via the manager
        task = asyncio.create_task(_run_task(hb, dict(task_row)))
        _running_tasks[task_row["id"]] = task
        started += 1

    if started > 0:
        logger.info("Sub-agent worker: started %d task(s)", started)
    return started


async def _run_task(hb, task_row: dict) -> None:
    """Run a single task via the manager and clean up the registry."""
    task_id = task_row["id"]
    try:
        await hb.subagent_manager.execute_task(task_row)
    except Exception:
        logger.exception("Sub-agent worker: execute_task raised for %s", task_id[:8])
    finally:
        _running_tasks.pop(task_id, None)


async def recover_orphaned_tasks(hb) -> int:
    """Mark tasks that have been running past their timeout as failed.

    Called on heartbeat startup to recover from crashes.
    """
    rows = await hb.db.fetch_all(
        "SELECT id, started_at, max_runtime_seconds FROM tasks "
        "WHERE type = 'subagent' AND status = 'running'",
    )
    recovered = 0
    now = datetime.now(timezone.utc)
    for row in rows:
        if not row["started_at"]:
            continue
        try:
            started = datetime.fromisoformat(row["started_at"].replace("Z", "+00:00"))
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
        except (ValueError, AttributeError):
            continue

        age = (now - started).total_seconds()
        limit = (row["max_runtime_seconds"] or 600) + ORPHAN_GRACE_SECONDS
        if age > limit:
            await hb.db.execute(
                "UPDATE tasks SET status = 'failed', "
                "error = 'interrupted (process restart)' WHERE id = ?",
                (row["id"],),
            )
            recovered += 1

    if recovered > 0:
        logger.info("Sub-agent worker: recovered %d orphaned task(s)", recovered)
    return recovered
