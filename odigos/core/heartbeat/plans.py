"""Heartbeat in-progress plan execution module."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from odigos.channels.base import UniversalMessage
from odigos.core.heartbeat.utils import log_heartbeat_session

if TYPE_CHECKING:
    from odigos.core.heartbeat.orchestrator import Heartbeat

logger = logging.getLogger(__name__)

_MAX_PLAN_RETRIES: int = 3
_FAIL_MARKERS = ("couldn't process", "having trouble reaching", "ran out of time", "went wrong")
_STUCK_STEP_THRESHOLD_MINUTES: int = 30


def _reset_stale_in_progress_steps(steps: list, plan_updated_at: str) -> bool:
    """Reset steps stuck in_progress past the staleness threshold to pending.

    Returns True if any steps were reset.
    """
    try:
        updated = datetime.fromisoformat(plan_updated_at.replace("Z", "+00:00"))
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return False

    age_minutes = (datetime.now(timezone.utc) - updated).total_seconds() / 60
    if age_minutes < _STUCK_STEP_THRESHOLD_MINUTES:
        return False

    has_stuck = False
    for s in steps:
        if s.get("status") == "in_progress":
            s["status"] = "pending"
            has_stuck = True
        for sub in s.get("substeps", []):
            if sub.get("status") == "in_progress":
                sub["status"] = "pending"
                has_stuck = True
    return has_stuck


async def build_plan_summary(db, plan_id: str) -> str:
    """Build a compact summary of a plan for headless context (~200-400 tokens)."""
    try:
        row = await db.fetch_one(
            "SELECT goal, steps FROM task_plans WHERE id = ?", (plan_id,)
        )
        if not row:
            return ""

        goal = row.get("goal") or "No goal specified"
        steps = json.loads(row["steps"])

        done_steps = [s for s in steps if s.get("status") == "done"]
        pending_steps = [s for s in steps if s.get("status") in (None, "pending", "in_progress")]

        lines = [f"Goal: {goal}"]
        lines.append(f"Progress: {len(done_steps)}/{len(steps)} steps complete")

        # Last 5 completed steps with result previews
        if done_steps:
            lines.append("\nCompleted:")
            for s in done_steps[-5:]:
                result_preview = (s.get("result") or "")[:80]
                suffix = f" -> {result_preview}" if result_preview else ""
                lines.append(f"  Step {s.get('step', '?')}: {s.get('task', '')[:100]}{suffix}")

        # Current/next pending steps
        if pending_steps:
            lines.append("\nRemaining:")
            for s in pending_steps[:3]:
                lines.append(f"  Step {s.get('step', '?')}: {s.get('task', '')[:100]}")

        return "\n".join(lines)
    except Exception:
        logger.debug("Could not build plan summary", exc_info=True)
        return ""


async def work_in_progress_plans(hb: "Heartbeat") -> bool:
    """Phase 4e: Pick up in-progress plans and execute the next pending step."""
    if hb._plan_fail_count >= _MAX_PLAN_RETRIES:
        return False

    try:
        row = await hb.db.fetch_one(
            "SELECT id, conversation_id, steps, goal, updated_at FROM task_plans "
            "WHERE status = 'in_progress' "
            "ORDER BY updated_at ASC LIMIT 1",
        )
        if not row:
            hb._plan_fail_count = 0
            return False

        steps = json.loads(row["steps"])

        # Reset any steps stuck in_progress past the staleness threshold
        # (handles crashes/silent failures mid-step execution)
        if _reset_stale_in_progress_steps(steps, row["updated_at"]):
            await hb.db.execute(
                "UPDATE task_plans SET steps = ?, updated_at = ? WHERE id = ?",
                (json.dumps(steps), datetime.now(timezone.utc).isoformat(), row["id"]),
            )
            logger.info(
                "Reset stale in_progress steps for plan %s (>%dm old)",
                row["id"][:8], _STUCK_STEP_THRESHOLD_MINUTES,
            )

        next_step = None
        for s in steps:
            if s.get("status") in (None, "pending"):
                next_step = s
                break
            for sub in s.get("substeps", []):
                if sub.get("status") in (None, "pending"):
                    next_step = sub
                    break
            if next_step:
                break

        if not next_step:
            # Check for stuck in_progress steps (reset them to pending)
            has_stuck = False
            for s in steps:
                if s.get("status") == "in_progress":
                    s["status"] = "pending"
                    has_stuck = True
                for sub in s.get("substeps", []):
                    if sub.get("status") == "in_progress":
                        sub["status"] = "pending"
                        has_stuck = True
            if has_stuck:
                await hb.db.execute(
                    "UPDATE task_plans SET steps = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(steps), datetime.now(timezone.utc).isoformat(), row["id"]),
                )
                logger.info("Reset stuck in_progress steps for plan %s", row["id"][:8])
                return False

            # All steps truly done, mark plan complete
            await hb.db.execute(
                "UPDATE task_plans SET status = 'done', updated_at = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), row["id"]),
            )
            return False

        step_desc = next_step.get("task", "")
        step_num = str(next_step.get("step", ""))
        plan_id = row["id"]
        conversation_id = row["conversation_id"]
        goal = row.get("goal")

        content = (
            f"Continue working on the plan. Execute step {step_num}: {step_desc}\n"
            f"When done, use update_plan to mark step {step_num} as done with your result."
        )

        metadata = {"plan_id": plan_id, "step": step_num}
        if goal:
            metadata["goal_id"] = goal

        message = UniversalMessage(
            id=str(uuid.uuid4()),
            channel="heartbeat",
            sender="system",
            content=content,
            timestamp=datetime.now(timezone.utc),
            metadata=metadata,
        )

        next_step["status"] = "in_progress"
        await hb.db.execute(
            "UPDATE task_plans SET steps = ?, updated_at = ? WHERE id = ?",
            (json.dumps(steps), datetime.now(timezone.utc).isoformat(), plan_id),
        )

        # Build plan summary for headless context
        plan_summary = await build_plan_summary(hb.db, plan_id)
        bg_model = getattr(hb, "background_model", "")

        hb.current_phase = "plans"
        hb.current_activity = f"Executing step {step_num}: {step_desc[:80]}"
        hb.current_plan = {
            "id": plan_id,
            "goal": goal or "",
            "current_step": int(step_num) if step_num.isdigit() else 0,
            "total_steps": len(steps),
            "conversation_id": conversation_id,
        }
        try:
            result = await hb.agent.handle_message(
                message,
                headless=True,
                plan_context=plan_summary,
                background_model=bg_model,
            )
        finally:
            hb.current_phase = None
            hb.current_activity = None
            hb.current_plan = None

        if result and any(m in result.lower() for m in _FAIL_MARKERS):
            hb._plan_fail_count += 1
            logger.warning(
                "Plan step failed (LLM error): %s (%d/%d)",
                result[:100], hb._plan_fail_count, _MAX_PLAN_RETRIES,
            )
            return False

        await log_heartbeat_session(
            hb,
            goal_id=goal,
            plan_id=plan_id,
            conversation_id=conversation_id,
            summary=f"Plan step {step_num}: {step_desc[:100]}. Result: {(result or '')[:300]}",
        )

        logger.info("Proactive plan step %s executed for plan %s", step_num, plan_id[:8])
        hb._plan_fail_count = 0
        return True
    except Exception:
        hb._plan_fail_count += 1
        logger.warning(
            "Proactive plan failed (%d/%d)", hb._plan_fail_count, _MAX_PLAN_RETRIES
        )
        return False
