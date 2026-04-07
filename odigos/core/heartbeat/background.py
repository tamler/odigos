"""Background task polling for the heartbeat loop."""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)


async def poll_pending_tasks(hb) -> bool:
    """Poll pending tasks (type=background_poll). Returns True if any work was done.

    Called from heartbeat _tick() as Phase 3c. Not budget-gated
    because polling is HTTP, not LLM.
    """
    rows = await hb.db.fetch_all(
        "SELECT * FROM tasks WHERE type = 'background_poll' AND status = 'pending' "
        "ORDER BY created_at LIMIT 5"
    )
    if not rows:
        return False

    did_work = False
    tool_registry = getattr(hb, "tool_registry", None)

    for task in rows:
        tool_name = task["tool_name"] or ""
        external_task_id = task["external_task_id"] or ""
        conversation_id = task["conversation_id"] or ""

        tool = tool_registry.get(tool_name) if tool_registry else None
        if not tool or not hasattr(tool, "complete_background"):
            logger.warning("Tool %s not available for background completion", tool_name)
            await hb.db.execute(
                "UPDATE tasks SET status = 'failed', error = 'Tool not available' WHERE id = ?",
                (task["id"],),
            )
            continue

        try:
            result = await tool.complete_background(external_task_id, conversation_id)

            if result.status == "pending":
                continue

            did_work = True

            if result.success:
                await hb.db.execute(
                    "UPDATE tasks SET status = 'completed', result_json = ?, "
                    "completed_at = datetime('now') WHERE id = ?",
                    (json.dumps(result.side_effect or {}), task["id"]),
                )

                if conversation_id:
                    await hb.message_bus.publish(
                        conversation_id=conversation_id,
                        role="system",
                        content=f"[Background task completed] {result.data}",
                        channel="heartbeat",
                        message_type="artifact" if result.side_effect else "notification",
                        metadata={
                            "tool_name": tool_name,
                            "task_id": task["id"],
                            "artifact": result.side_effect.get("artifact") if result.side_effect else None,
                        },
                        idempotency_key=f"bg-{task['id']}",
                    )
            else:
                await hb.db.execute(
                    "UPDATE tasks SET status = 'failed', error = ? WHERE id = ?",
                    ((result.error or "Unknown error")[:500], task["id"]),
                )
                if hb.notifier:
                    await hb.notifier.notify(
                        title=f"{tool_name} failed",
                        body=result.error or "Unknown error",
                        conversation_id=conversation_id,
                    )

        except Exception:
            logger.exception("Background poll failed for task %s", task["id"])
            await hb.db.execute(
                "UPDATE tasks SET retry_count = retry_count + 1 WHERE id = ?",
                (task["id"],),
            )
            await hb.db.execute(
                "UPDATE tasks SET status = 'failed', error = 'Max retries exceeded' "
                "WHERE id = ? AND retry_count >= max_retries",
                (task["id"],),
            )

    return did_work
