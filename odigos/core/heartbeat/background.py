"""Background task polling for the heartbeat loop."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

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

                # Inject system message into conversation
                if conversation_id:
                    await hb.db.execute(
                        "INSERT INTO messages (id, conversation_id, role, content, created_at) "
                        "VALUES (?, ?, 'system', ?, datetime('now'))",
                        (str(uuid.uuid4()), conversation_id,
                         f"[Background task completed] {result.data}"),
                    )

                # Notify user
                if hb.notifier:
                    await hb.notifier.notify(
                        title=f"{tool_name} complete",
                        body=result.data,
                        conversation_id=conversation_id,
                    )

                # Send task_completed WebSocket event
                web_channel = hb.channel_registry.get("web") if hb.channel_registry else None
                if web_channel and hasattr(web_channel, "broadcast"):
                    await web_channel.broadcast({
                        "type": "task_completed",
                        "task_id": task["id"],
                        "tool_name": tool_name,
                        "conversation_id": conversation_id,
                        "result": result.data,
                        "artifact": result.side_effect.get("artifact") if result.side_effect else None,
                    })
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
