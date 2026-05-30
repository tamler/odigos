"""Generic callback endpoint for external API results.

External APIs POST to /api/callbacks/{task_id} when async work completes.
External APIs can't carry our session/api-key, so this route is public, but
each callback URL we hand out is HMAC-signed over the task_id (query param
?sig=...). The signature is verified here before any task processing, so a
leaked task_id alone is not enough to forge a completion.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/callbacks", tags=["callbacks"])
logger = logging.getLogger(__name__)


def _callback_sig(secret: str, task_id: str) -> str:
    """HMAC-SHA256 signature over the task_id, hex-encoded.

    Shared by the URL generator (which appends ?sig=...) and the handler
    (which verifies it) so the two never drift.
    """
    return hmac.new(secret.encode(), task_id.encode(), hashlib.sha256).hexdigest()


@router.post("/{task_id}")
async def handle_callback(task_id: str, request: Request):
    """Receive callback from external API when async task completes."""
    container = request.app.state.container

    # Verify the HMAC signature before touching the body or task. The signature
    # is computed over the task_id with session_secret; a missing or mismatched
    # signature is rejected so a leaked task_id can't be used to forge results.
    secret = container.settings.session_secret if container.settings else ""
    sig = request.query_params.get("sig", "")
    expected = _callback_sig(secret, task_id) if secret else ""
    if not secret or not sig or not hmac.compare_digest(sig, expected):
        logger.warning("Callback with invalid/missing signature for task %s", task_id[:12])
        raise HTTPException(status_code=403, detail="Invalid callback signature")

    db = container.db
    if not db:
        return JSONResponse({"error": "not ready"}, status_code=503)

    # Look up the task
    task = await db.fetch_one(
        "SELECT * FROM tasks WHERE id = ? AND type = 'background_poll'",
        (task_id,),
    )
    if not task:
        logger.warning("Callback for unknown task: %s", task_id[:12])
        return JSONResponse({"error": "unknown task"}, status_code=404)

    if task["status"] not in ("pending", "callback_received"):
        logger.info("Callback for already-completed task: %s", task_id[:12])
        return JSONResponse({"status": "already_processed"})

    # Limit payload size (prevent abuse on unauthenticated endpoint)
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > 500_000:  # 500KB max
        return JSONResponse({"error": "payload too large"}, status_code=413)

    # Store the callback payload
    try:
        body = await request.json()
    except Exception:
        raw = await request.body()
        if len(raw) > 500_000:
            return JSONResponse({"error": "payload too large"}, status_code=413)
        body = {"raw": raw.decode(errors="replace")[:5000]}

    # Kie.ai sends multiple callbacks: "text" (lyrics ready) then "complete" (audio ready).
    # Only process "complete" callbacks. Store others but don't trigger completion.
    callback_type = body.get("data", {}).get("callbackType", "")
    if callback_type and callback_type != "complete":
        logger.info("Callback type '%s' for task %s — waiting for 'complete'", callback_type, task_id[:12])
        await db.execute(
            "UPDATE tasks SET result_json = ? WHERE id = ?",
            (json.dumps(body), task_id),
        )
        return JSONResponse({"status": "waiting_for_complete"})

    await db.execute(
        "UPDATE tasks SET result_json = ?, status = 'callback_received' WHERE id = ?",
        (json.dumps(body), task_id),
    )
    logger.info("Callback received for task %s (tool: %s)", task_id[:12], task["tool_name"])

    # Try to complete the task immediately
    tool_registry = request.app.state.container.tool_registry
    tool = tool_registry.get(task["tool_name"]) if tool_registry else None

    if tool and hasattr(tool, "complete_from_callback"):
        try:
            result = await tool.complete_from_callback(
                task_id=task["external_task_id"],
                conversation_id=task["conversation_id"] or "",
                callback_data=body,
            )

            if result.success:
                await db.execute(
                    "UPDATE tasks SET status = 'completed', result_json = ?, "
                    "completed_at = datetime('now') WHERE id = ?",
                    (json.dumps(result.side_effect or {}), task_id),
                )

                conversation_id = task["conversation_id"] or ""
                if conversation_id:
                    container = request.app.state.container
                    await container.message_bus.publish(
                        conversation_id=conversation_id,
                        role="system",
                        content=f"[Background task completed] {result.data}",
                        channel="callback",
                        message_type="artifact" if result.side_effect else "notification",
                        metadata={
                            "tool_name": task["tool_name"],
                            "task_id": task_id,
                            "artifact": result.side_effect.get("artifact") if result.side_effect else None,
                        },
                        idempotency_key=f"callback-{task_id}",
                    )

                logger.info("Task %s completed via callback", task_id[:12])
            else:
                await db.execute(
                    "UPDATE tasks SET status = 'failed', error = ? WHERE id = ?",
                    ((result.error or "Callback processing failed")[:500], task_id),
                )
        except Exception:
            logger.exception("Callback processing failed for task %s", task_id[:12])
            await db.execute(
                "UPDATE tasks SET status = 'failed', error = 'Callback processing error' WHERE id = ?",
                (task_id,),
            )
    else:
        # Tool doesn't have complete_from_callback — mark as callback_received
        # and let the heartbeat poller pick it up
        logger.info("Task %s callback stored, will be processed by poller", task_id[:12])

    return JSONResponse({"status": "ok"})
