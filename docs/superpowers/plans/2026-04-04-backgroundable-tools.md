# Backgroundable Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Long-running tools return immediately with `status="pending"`, the heartbeat polls in the background, and results are delivered via WebSocket + system message injection.

**Architecture:** Tools submit API tasks and return `status="pending"` with a `task_id`. The executor detects pending results and stores them in the `tasks` table. A new heartbeat phase polls pending tasks via `poll_once()`, downloads artifacts on completion, injects system messages, and sends WebSocket notifications.

**Tech Stack:** Python 3.12, aiosqlite, pytest, httpx

**Spec:** `docs/superpowers/specs/2026-04-04-backgroundable-tools-design.md`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `odigos/tools/api_tool.py` | Add `poll_once()` method |
| `odigos/tools/image_gen.py` | Return pending from execute(), add complete_background() |
| `odigos/tools/music_gen.py` | Same pattern as image_gen |
| `odigos/core/executor.py` | Detect pending results, store in tasks table |
| `odigos/core/heartbeat/background.py` | **New** — poll_background_tasks() function |
| `odigos/core/heartbeat/orchestrator.py` | Add Phase 3c, add tool_registry param |
| `odigos/bootstrap.py` | Pass tool_registry to Heartbeat |
| `tests/test_background_tools.py` | **New** — tests for poll_once, pending detection, background polling |

---

### Task 1: Add poll_once() to APITool and write tests

**Files:**
- Modify: `odigos/tools/api_tool.py`
- Create: `tests/test_background_tools.py`

- [ ] **Step 1: Write tests for poll_once**

Create `tests/test_background_tools.py`:

```python
"""Tests for backgroundable tools: poll_once, pending detection, background polling."""
import json
import pytest
import httpx

from odigos.tools.api_tool import APITool, ToolAPIError
from odigos.tools.base import ToolResult


class FakeBgTool(APITool):
    name = "fake_bg"
    description = "Test backgroundable tool"
    async def execute(self, params: dict) -> ToolResult:
        return ToolResult(success=True, data="ok")


class TestPollOnce:
    @pytest.mark.asyncio
    async def test_poll_once_done(self, httpx_mock):
        """Returns ('done', extracted) when success_check passes."""
        httpx_mock.add_response(
            url="https://api.example.com/poll",
            json={"status": "done", "result": "image.png"},
        )
        client = httpx.AsyncClient()
        tool = FakeBgTool(http=client)
        status, result = await tool.poll_once(
            "https://api.example.com/poll",
            api_key="test",
            params={"taskId": "t1"},
            success_check=lambda d: d.get("status") == "done",
            failure_check=lambda d: d.get("status") == "failed",
            extract=lambda d: d["result"],
        )
        assert status == "done"
        assert result == "image.png"
        await client.aclose()

    @pytest.mark.asyncio
    async def test_poll_once_pending(self, httpx_mock):
        """Returns ('pending', None) when still processing."""
        httpx_mock.add_response(
            url="https://api.example.com/poll",
            json={"status": "processing"},
        )
        client = httpx.AsyncClient()
        tool = FakeBgTool(http=client)
        status, result = await tool.poll_once(
            "https://api.example.com/poll",
            api_key="test",
            params={},
            success_check=lambda d: d.get("status") == "done",
            failure_check=lambda d: d.get("status") == "failed",
            extract=lambda d: d["result"],
        )
        assert status == "pending"
        assert result is None
        await client.aclose()

    @pytest.mark.asyncio
    async def test_poll_once_failed(self, httpx_mock):
        """Returns ('failed', data) when failure_check passes."""
        httpx_mock.add_response(
            url="https://api.example.com/poll",
            json={"status": "failed", "error": "bad input"},
        )
        client = httpx.AsyncClient()
        tool = FakeBgTool(http=client)
        status, result = await tool.poll_once(
            "https://api.example.com/poll",
            api_key="test",
            params={},
            success_check=lambda d: d.get("status") == "done",
            failure_check=lambda d: d.get("status") == "failed",
            extract=lambda d: d["result"],
        )
        assert status == "failed"
        assert result["error"] == "bad input"
        await client.aclose()
```

- [ ] **Step 2: Implement poll_once()**

Add to `odigos/tools/api_tool.py` after `poll_until()`:

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

- [ ] **Step 3: Run tests**

Run: `python3 -m pytest tests/test_background_tools.py::TestPollOnce -v`
Expected: 3/3 PASS

- [ ] **Step 4: Commit**

```bash
git add odigos/tools/api_tool.py tests/test_background_tools.py
git commit -m "feat(tools): add poll_once() for single-attempt background polling"
```

---

### Task 2: Modify image_gen to return pending

**Files:**
- Modify: `odigos/tools/image_gen.py`

- [ ] **Step 1: Modify execute() to return pending**

Read `odigos/tools/image_gen.py`. Change `execute()` so that after `_create_task()` succeeds, it returns immediately with `status="pending"` instead of calling `_poll_result()`. The task_id, conversation_id, and arguments go in `side_effect.background_task`.

The new flow:
1. Validate params (unchanged)
2. Call `_create_task()` to get external task_id (unchanged)
3. Return `ToolResult(success=True, status="pending", task_id=task_id, data="Image generation started...", side_effect={"background_task": {...}})`

The old polling + download + artifact code moves to a new `complete_background()` method.

- [ ] **Step 2: Add complete_background() method**

Add `complete_background(self, task_id: str, conversation_id: str) -> ToolResult` that:
1. Calls `self.poll_once()` with the same success/failure checks as the old `_poll_result()`
2. If "pending", returns `ToolResult(success=True, status="pending", data="Still processing...")`
3. If "failed", returns `ToolResult(success=False, ...)`
4. If "done", downloads the image via `_download_image()`, stores artifact in DB, returns success with artifact side_effect

- [ ] **Step 3: Verify syntax**

Run: `python3 -c "from odigos.tools.image_gen import GenerateImageTool; print('OK')"`

- [ ] **Step 4: Commit**

```bash
git add odigos/tools/image_gen.py
git commit -m "feat(image_gen): return pending immediately, add complete_background()"
```

---

### Task 3: Modify music_gen to return pending

**Files:**
- Modify: `odigos/tools/music_gen.py`

- [ ] **Step 1: Same pattern as image_gen**

Read `odigos/tools/music_gen.py`. Apply the same changes:
1. `execute()` calls `_create_task()` and returns `status="pending"` immediately
2. New `complete_background()` method: calls `poll_once()`, if done downloads all tracks, stores artifacts

Note: music_gen returns multiple tracks. `complete_background()` must handle the multi-track download loop that currently lives in `execute()`.

- [ ] **Step 2: Verify syntax**

Run: `python3 -c "from odigos.tools.music_gen import GenerateMusicTool; print('OK')"`

- [ ] **Step 3: Commit**

```bash
git add odigos/tools/music_gen.py
git commit -m "feat(music_gen): return pending immediately, add complete_background()"
```

---

### Task 4: Executor detects pending, stores in tasks table

**Files:**
- Modify: `odigos/core/executor.py`
- Add to: `tests/test_background_tools.py`

- [ ] **Step 1: Write test for pending detection**

Add to `tests/test_background_tools.py`:

```python
class TestPendingDetection:
    @pytest.mark.asyncio
    async def test_store_background_task(self, fake_db):
        """Executor stores background task in tasks table when status=pending."""
        from odigos.core.executor import _store_background_task

        bg_info = {
            "tool_name": "generate_image",
            "external_task_id": "ext123",
            "conversation_id": "conv456",
            "arguments": {"prompt": "sunset"},
        }
        task_id = await _store_background_task(fake_db, bg_info)
        assert task_id is not None

        row = await fake_db.fetch_one(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        )
        assert row["type"] == "background_poll"
        assert row["status"] == "pending"
        assert "generate_image" in row["payload_json"]
```

Update the `fake_db` fixture in `tests/conftest.py` to also create the `tasks` table:

```sql
CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    description TEXT,
    payload_json TEXT,
    conversation_id TEXT,
    result_json TEXT,
    error TEXT,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    started_at TEXT,
    completed_at TEXT,
    created_by TEXT DEFAULT 'system',
    created_at TEXT DEFAULT (datetime('now'))
)
```

- [ ] **Step 2: Implement _store_background_task in executor.py**

Add as module-level function:

```python
async def _store_background_task(db, background_info: dict) -> str:
    """Store a pending background task for heartbeat polling."""
    import json as _json
    task_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO tasks (id, type, status, description, payload_json, "
        "conversation_id, created_by) "
        "VALUES (?, 'background_poll', 'pending', ?, ?, ?, 'system')",
        (
            task_id,
            f"Background: {background_info['tool_name']}",
            _json.dumps(background_info),
            background_info.get("conversation_id", ""),
        ),
    )
    return task_id
```

- [ ] **Step 3: Integrate into _execute_tool**

In `_execute_tool`, after the experience feedback block (line 746) and before `if result.success:` (line 748), add:

```python
            # Background task: store for heartbeat polling and return immediately
            if result and result.status == "pending":
                bg = result.side_effect.get("background_task") if result.side_effect else None
                if bg and self.db:
                    await _store_background_task(self.db, bg)
                return result.data
```

This short-circuits the normal return path — the pending message goes to the LLM without format_for_context processing.

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_background_tools.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add odigos/core/executor.py tests/test_background_tools.py tests/conftest.py
git commit -m "feat(executor): detect pending tool results, store background tasks"
```

---

### Task 5: Heartbeat background polling phase

**Files:**
- Create: `odigos/core/heartbeat/background.py`
- Modify: `odigos/core/heartbeat/orchestrator.py`
- Modify: `odigos/bootstrap.py`

- [ ] **Step 1: Create background.py**

Create `odigos/core/heartbeat/background.py` with the `poll_background_tasks(hb)` function.

Read the spec section 5 for the full implementation. Key points:
- Query `tasks WHERE type='background_poll' AND status='pending' LIMIT 5`
- For each task, look up the tool from `hb.tool_registry`
- Call `tool.complete_background(external_task_id, conversation_id)`
- If "done": update task to completed, inject system message into conversation, notify via WebSocket
- If "pending": update `started_at` timestamp, continue
- If failed or exception: increment retry_count, mark failed after max_retries
- Returns `True` if any work was done

The function needs: `hb.db`, `hb.tool_registry`, `hb.notifier`, `hb.channel_registry`

- [ ] **Step 2: Add tool_registry to Heartbeat.__init__**

In `odigos/core/heartbeat/orchestrator.py`, add `tool_registry=None` parameter to `__init__()` and store as `self.tool_registry = tool_registry`.

- [ ] **Step 3: Add Phase 3c to _tick()**

In `_tick()`, after Phase 3b (line 157: `did_work |= await maintenance.run_cron_jobs(self)`) and before Phase 4 (line 159), add:

```python
        # Phase 3c: Poll pending background tasks (HTTP only, no LLM)
        from odigos.core.heartbeat import background
        did_work |= await background.poll_background_tasks(self)
```

Not budget-gated — this is HTTP polling, not LLM calls.

- [ ] **Step 4: Pass tool_registry in bootstrap.py**

In `odigos/bootstrap.py`, find the Heartbeat constructor call (line 876) and add:

```python
            tool_registry=self.container.tool_registry,
```

- [ ] **Step 5: Verify syntax**

Run:
```bash
python3 -c "from odigos.core.heartbeat.background import poll_background_tasks; print('OK')"
python3 -c "from odigos.core.heartbeat import Heartbeat; print('OK')"
```

- [ ] **Step 6: Commit**

```bash
git add odigos/core/heartbeat/background.py odigos/core/heartbeat/orchestrator.py odigos/bootstrap.py
git commit -m "feat(heartbeat): add background task polling phase"
```

---

### Task 6: Integration verification

- [ ] **Step 1: Run all tests**

Run: `python3 -m pytest tests/test_background_tools.py tests/test_tools.py tests/test_api_tool.py tests/test_xskill.py tests/test_graph.py tests/test_executor_validation.py tests/test_cli_tool.py -q`
Expected: All pass

- [ ] **Step 2: Verify imports chain**

Run:
```bash
python3 -c "
from odigos.tools.api_tool import APITool
from odigos.tools.image_gen import GenerateImageTool
from odigos.tools.music_gen import GenerateMusicTool
from odigos.core.executor import _store_background_task
from odigos.core.heartbeat.background import poll_background_tasks
print('All backgroundable tools imports OK')
print(f'image_gen has complete_background: {hasattr(GenerateImageTool, \"complete_background\")}')
print(f'music_gen has complete_background: {hasattr(GenerateMusicTool, \"complete_background\")}')
"
```

- [ ] **Step 3: Commit any fixes**

```bash
git add -A && git commit -m "fix: backgroundable tools integration cleanup"
```
