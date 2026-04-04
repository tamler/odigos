# Backgroundable Tools Design

**Date:** 2026-04-04
**Status:** Approved
**Goal:** Long-running tools return immediately with `status="pending"`, the heartbeat polls in the background, and results are delivered via WebSocket notification + system message injection.

## Context

Image generation blocks the executor for 2-3 minutes. Music generation blocks for 3+ minutes. During this time the user sees a spinner and can't interact. Backgroundable tools fix this: the tool submits the API task, returns immediately, and the heartbeat handles polling/delivery in the background.

Infrastructure already in place:
- `ToolResult.status` and `task_id` fields (Phase 1)
- `tasks` table with `type`, `status`, `payload_json`, `result_json`, `conversation_id`
- WebSocket `task_completed` message type (frontend already handles it)
- Notifier supports `conversation_id` targeting
- Heartbeat has clear insertion point for new phase

## Decisions

| Question | Decision | Rationale |
|----------|----------|-----------|
| Storage | Existing `tasks` table with `type="background_poll"` | No migration needed. Table already has all required fields. |
| Polling strategy | `poll_once()` per heartbeat tick (every 30s) | No blocking loops. Heartbeat naturally provides the interval. |
| User notification | WebSocket `task_completed` + toast (already wired) | Frontend already handles this message type. |
| Agent notification | System message injection into conversation | Agent sees result in history, can reference it naturally. |
| Opt-in mechanism | Tool returns `status="pending"` from `execute()` | Generic — any tool can opt in without executor changes. |
| Frontend | Deferred to Gemini handoff | Backend is the architectural work; frontend is UI polish. |

## Design

### 1. APITool: `poll_once()` Method

**Modified file:** `odigos/tools/api_tool.py`

```python
async def poll_once(
    self,
    url: str,
    api_key: str,
    params: dict,
    success_check: Callable[[dict], bool],
    failure_check: Callable[[dict], bool],
    extract: Callable[[dict], Any],
) -> tuple[str, Any]:
    """Single poll attempt for background tasks.

    Returns:
        ("done", extracted_result) on success
        ("failed", error_data) on failure
        ("pending", None) if still processing
    """
    data = await self.api_get(url, api_key, params)
    if success_check(data):
        return "done", extract(data)
    if failure_check(data):
        return "failed", data
    return "pending", None
```

Existing `poll_until()` stays for any future synchronous use. `poll_once()` is for heartbeat-driven polling.

### 2. Tool Changes: image_gen and music_gen

**Modified files:** `odigos/tools/image_gen.py`, `odigos/tools/music_gen.py`

Tools gain two modes:
- `execute()` — submits the API task, returns `status="pending"` immediately
- `complete_background(task_id, conversation_id)` — called by heartbeat to poll, download, store artifact

**image_gen.py execute() changes:**

```python
async def execute(self, params: dict) -> ToolResult:
    conversation_id = params.pop("_conversation_id", None)
    prompt = (params.get("prompt") or "").strip()
    # ... validation ...

    try:
        task_id = await self._create_task(prompt, ratio)
        return ToolResult(
            success=True,
            status="pending",
            task_id=task_id,
            data=f"Image generation started for: {prompt[:80]}. I'll notify you when it's ready.",
            side_effect={
                "background_task": {
                    "tool_name": self.name,
                    "external_task_id": task_id,
                    "conversation_id": conversation_id,
                    "arguments": {"prompt": prompt, "aspect_ratio": ratio},
                }
            },
        )
    except ToolAPIError as e:
        return ToolResult(success=False, data="", error=e.message,
                         failure_category=e.failure_category)
```

**image_gen.py complete_background():**

```python
async def complete_background(self, task_id: str, conversation_id: str) -> ToolResult:
    """Poll once and complete if ready. Called by heartbeat."""
    status, result = await self.poll_once(
        f"{KIE_BASE}/jobs/recordInfo",
        api_key=self._api_key,
        params={"taskId": task_id},
        success_check=lambda d: d.get("code") == 200 and d.get("data", {}).get("state") == "success",
        failure_check=lambda d: d.get("code") == 200 and d.get("data", {}).get("state") == "fail",
        extract=lambda d: json.loads(d["data"].get("resultJson", "{}")).get("resultUrls", [None])[0],
    )

    if status == "pending":
        return ToolResult(success=True, status="pending", data="Still processing...")

    if status == "failed":
        return ToolResult(success=False, data="", error="Image generation failed")

    # status == "done" — download and store artifact
    image_url = result
    # ... same download + artifact storage logic as current execute() ...
    return ToolResult(success=True, data=f"Image generated: {filename} ({file_size} bytes)",
                     side_effect={"artifact": {...}})
```

music_gen follows the same pattern.

### 3. Executor: Detect Pending, Store Task

**Modified file:** `odigos/core/executor.py`

In `_execute_tool`, after the result is processed but before returning, detect `status="pending"`:

```python
# After experience feedback, before final return
if result and result.status == "pending" and result.side_effect:
    bg = result.side_effect.get("background_task")
    if bg and self.db:
        import json as _json
        await self.db.execute(
            "INSERT INTO tasks (id, type, status, description, payload_json, "
            "conversation_id, created_by, created_at) "
            "VALUES (?, 'background_poll', 'pending', ?, ?, ?, 'system', datetime('now'))",
            (
                str(uuid.uuid4()),
                f"Background: {bg['tool_name']}",
                _json.dumps(bg),
                bg.get("conversation_id", ""),
            ),
        )
```

The executor then returns `result.data` normally — the LLM tells the user the task is started.

### 4. System Message Injection on Completion

When a background task completes, inject a system message into the conversation so the agent knows the result on the next turn.

**In the heartbeat background poller (see section 5):**

```python
# After task completes successfully
if conversation_id:
    await hb.db.execute(
        "INSERT INTO messages (id, conversation_id, role, content, created_at) "
        "VALUES (?, ?, 'system', ?, datetime('now'))",
        (str(uuid.uuid4()), conversation_id,
         f"[Background task completed] {tool_result.data}"),
    )
```

The agent sees this in conversation history on the next turn. The frontend can render system messages with a distinct style.

### 5. Heartbeat: Background Task Polling Phase

**New file:** `odigos/core/heartbeat/background.py`

```python
async def poll_background_tasks(hb) -> bool:
    """Poll pending background tasks. Returns True if any work was done."""
    import json

    rows = await hb.db.fetch_all(
        "SELECT * FROM tasks WHERE type = 'background_poll' AND status = 'pending' "
        "ORDER BY created_at LIMIT 5"
    )
    if not rows:
        return False

    did_work = False
    for task in rows:
        payload = json.loads(task["payload_json"])
        tool_name = payload["tool_name"]
        external_task_id = payload["external_task_id"]
        conversation_id = task.get("conversation_id", "")

        tool = hb.tool_registry.get(tool_name) if hasattr(hb, 'tool_registry') else None
        if not tool or not hasattr(tool, "complete_background"):
            # Tool not found or doesn't support background completion
            await hb.db.execute(
                "UPDATE tasks SET status = 'failed', error = 'Tool not available' WHERE id = ?",
                (task["id"],),
            )
            continue

        try:
            result = await tool.complete_background(external_task_id, conversation_id)

            if result.status == "pending":
                # Still processing — update last_polled timestamp
                await hb.db.execute(
                    "UPDATE tasks SET started_at = datetime('now') WHERE id = ?",
                    (task["id"],),
                )
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
                    import uuid as _uuid
                    await hb.db.execute(
                        "INSERT INTO messages (id, conversation_id, role, content, created_at) "
                        "VALUES (?, ?, 'system', ?, datetime('now'))",
                        (str(_uuid.uuid4()), conversation_id,
                         f"[Background task completed] {result.data}"),
                    )

                # Notify user via WebSocket + push
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
            import logging
            logging.getLogger(__name__).exception("Background poll failed for task %s", task["id"])
            await hb.db.execute(
                "UPDATE tasks SET retry_count = retry_count + 1 WHERE id = ?",
                (task["id"],),
            )
            # Mark as failed after max retries
            await hb.db.execute(
                "UPDATE tasks SET status = 'failed', error = 'Max retries exceeded' "
                "WHERE id = ? AND retry_count >= max_retries",
                (task["id"],),
            )

    return did_work
```

**Modified file:** `odigos/core/heartbeat/orchestrator.py`

Add Phase 3c in `_tick()` after subagent delivery:

```python
# Phase 3c: Poll pending background tasks (no LLM, just HTTP polling)
from odigos.core.heartbeat import background
did_work |= await background.poll_background_tasks(self)
```

Not budget-gated — polling is HTTP, not LLM.

### 6. Tool Registry Access in Heartbeat

The heartbeat needs access to the tool registry to look up tools for `complete_background()`. 

**Modified file:** `odigos/core/heartbeat/orchestrator.py`

Add `tool_registry` to `__init__`:

```python
def __init__(self, ..., tool_registry=None, ...):
    ...
    self.tool_registry = tool_registry
```

**Modified file:** `odigos/bootstrap.py`

Pass tool registry when creating heartbeat (it's already available at that point since heartbeat is Phase 7, tools are Phase 5).

## File Change Summary

| File | Change |
|------|--------|
| `odigos/tools/api_tool.py` | Add `poll_once()` method |
| `odigos/tools/image_gen.py` | `execute()` returns pending, add `complete_background()` |
| `odigos/tools/music_gen.py` | Same pattern as image_gen |
| `odigos/core/executor.py` | Detect `status="pending"`, store in `tasks` table |
| `odigos/core/heartbeat/background.py` | **New** — `poll_background_tasks(hb)` |
| `odigos/core/heartbeat/orchestrator.py` | Add Phase 3c, add `tool_registry` to `__init__` |
| `odigos/bootstrap.py` | Pass `tool_registry` to Heartbeat constructor |

## What Doesn't Change

- `tasks` table schema — no migration
- `poll_until()` on APITool — stays for synchronous use
- WebSocket protocol — `task_completed` already handled by frontend
- Notifier — already supports conversation_id
- Local tools (code, file, etc.) — synchronous, unaffected
- Frontend — deferred to Gemini handoff

## Gemini Frontend Handoff

The backend sends `task_completed` WebSocket messages. The frontend needs:

1. **uiStore addition**: `backgroundTasks: {id: string, toolName: string, status: string, startedAt: string}[]`
2. **WebSocket handler update**: On `task_completed`, remove from backgroundTasks array, show toast
3. **BackgroundTaskIndicator component**: Scrolling status message near the input area or in the loading messages showing active background tasks (e.g., "Generating image... Composing music...")
4. **System message rendering**: Style `role="system"` messages with `[Background task completed]` prefix distinctly in the message list

This is UI polish work — the backend delivers all the data, Gemini just needs to render it.
