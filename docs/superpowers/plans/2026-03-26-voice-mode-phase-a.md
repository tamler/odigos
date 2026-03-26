# Voice Mode & Message Actions — Phase A Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add message hover actions (copy/speak/report/retry/edit), stop button, TTS filtering, auto-read, voice detection fix, concise mode, and TTS endpoint hardening.

**Architecture:** Backend-first for cancel, report, concise mode, and TTS fixes. Frontend tasks are self-contained and delegated to Gemini via handoff doc. Backend exposes the APIs; frontend consumes them.

**Tech Stack:** Python/FastAPI (backend), React/TypeScript/Tailwind (frontend), edge-tts, Groq Whisper, lucide-react icons, sonner toasts.

**Spec:** `docs/superpowers/specs/2026-03-26-voice-mode-design.md`

---

## Chunk 1: Backend Tasks (Claude)

### Task 1: Report Endpoint

**Files:**
- Create: `odigos/api/report.py`
- Create: `tests/test_report_api.py`
- Modify: `odigos/main.py` (mount router)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_report_api.py
"""Tests for message report endpoint."""
import pytest
from types import SimpleNamespace
from fastapi import FastAPI
from starlette.testclient import TestClient


def _make_app():
    from odigos.api.report import router
    app = FastAPI()
    app.include_router(router)
    app.state.settings = SimpleNamespace(
        api_key="test-key",
        session_secret="",
    )

    # Mock DB
    class MockDB:
        def __init__(self):
            self.inserts = []

        async def execute(self, sql, params=None):
            self.inserts.append((sql, params))

    app.state.db = MockDB()
    return app


class TestReportEndpoint:
    def test_report_creates_evaluation(self):
        app = _make_app()
        client = TestClient(app)
        resp = client.post(
            "/api/conversations/conv-123/report",
            json={"message_index": 2, "reason": "wrong", "message_content": "bad answer"},
            headers={"Authorization": "Bearer test-key"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "reported"
        assert len(app.state.db.inserts) == 1
        sql, params = app.state.db.inserts[0]
        assert "evaluations" in sql
        assert params[2] == "conv-123"  # conversation_id

    def test_report_requires_auth(self):
        app = _make_app()
        client = TestClient(app)
        resp = client.post(
            "/api/conversations/conv-123/report",
            json={"message_index": 0, "reason": "unhelpful", "message_content": "x"},
        )
        assert resp.status_code == 401

    def test_report_validates_reason(self):
        app = _make_app()
        client = TestClient(app)
        resp = client.post(
            "/api/conversations/conv-123/report",
            json={"message_index": 0, "reason": "invalid-reason", "message_content": "x"},
            headers={"Authorization": "Bearer test-key"},
        )
        assert resp.status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_report_api.py -x -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Write the report endpoint**

```python
# odigos/api/report.py
"""Message report endpoint — user flags bad/unhelpful responses."""
from __future__ import annotations

import uuid
from enum import Enum

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from odigos.api.deps import require_auth


router = APIRouter(
    prefix="/api/conversations",
    dependencies=[Depends(require_auth)],
)


class ReportReason(str, Enum):
    wrong = "wrong"
    unhelpful = "unhelpful"
    harmful = "harmful"


class ReportBody(BaseModel):
    message_index: int
    reason: ReportReason
    message_content: str


@router.post("/{conversation_id}/report")
async def report_message(
    conversation_id: str,
    body: ReportBody,
    request: Request,
):
    """Flag a message as bad. Creates a negative evaluation record for AREW."""
    db = request.app.state.db
    eval_id = uuid.uuid4().hex[:16]

    await db.execute(
        "INSERT INTO evaluations (id, message_id, conversation_id, task_type, "
        "overall_score, improvement_signal, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
        (
            eval_id,
            f"msg-{body.message_index}",
            conversation_id,
            "user_report",
            -1.0,
            f"User reported: {body.reason.value} — {body.message_content[:200]}",
        ),
    )

    return {"status": "reported", "evaluation_id": eval_id}
```

- [ ] **Step 4: Mount the router in main.py**

Find the router includes section in `odigos/main.py` and add:
```python
from odigos.api.report import router as report_router
app.include_router(report_router)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_report_api.py -x -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add odigos/api/report.py tests/test_report_api.py odigos/main.py
git commit -m "feat: add message report endpoint for user feedback into AREW"
```

---

### Task 2: Cancel Mechanism (WebSocket + Executor)

**Files:**
- Modify: `odigos/api/ws.py`
- Modify: `odigos/core/executor.py` (already has `abort_event` — reuse it)
- Create: `tests/test_cancel_ws.py`

The executor already accepts `abort_event: asyncio.Event | None` and checks it at each turn. We just need to:
1. Create a per-connection cancel event in ws.py
2. Handle `{"type": "cancel"}` messages to set it
3. Thread the event through agent_service → agent → executor

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cancel_ws.py
"""Tests for cancel event threading through agent service."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from odigos.core.agent_service import AgentService


class TestCancelEventThreading:
    @pytest.mark.asyncio
    async def test_abort_event_passed_to_agent(self):
        """AgentService.handle_message should forward abort_event to agent."""
        mock_agent = MagicMock()
        mock_agent.handle_message = AsyncMock(return_value="ok")

        service = AgentService.__new__(AgentService)
        service.agent = mock_agent
        service.budget_tracker = None
        service.approval_gate = None

        cancel = asyncio.Event()
        from odigos.channels.base import UniversalMessage
        from datetime import datetime, timezone
        msg = UniversalMessage(
            id="test", channel="web", sender="u",
            content="hi", timestamp=datetime.now(timezone.utc),
        )
        await service.handle_message(msg, abort_event=cancel)
        mock_agent.handle_message.assert_called_once()
        _, kwargs = mock_agent.handle_message.call_args
        assert kwargs["abort_event"] is cancel

    @pytest.mark.asyncio
    async def test_abort_event_stops_executor_loop(self):
        """When abort_event is set, executor should stop at next turn check."""
        event = asyncio.Event()
        event.set()  # Pre-set to simulate cancel
        # The executor checks abort_event at the top of each turn loop
        # and breaks if set. This is already implemented in executor.py:142-144.
        assert event.is_set()
```

- [ ] **Step 2: Modify ws.py to handle cancel messages**

In `websocket_endpoint()`, add a `cancel_event` and handle the cancel message type.

In the main message loop (after the `elif msg_type == "subscribe":` block), add:
```python
elif msg_type == "cancel":
    if cancel_event is not None:
        cancel_event.set()
        try:
            await websocket.send_json({
                "type": "stream_end",
                "cancelled": True,
                "conversation_id": conversation_id,
            })
        except Exception:
            pass
```

At the top of `websocket_endpoint()`, after `processor_task`, add:
```python
cancel_event: asyncio.Event | None = None
```

In `_process_chat_queue()`, before calling `agent_service.handle_message()`:
```python
nonlocal cancel_event
cancel_event = asyncio.Event()
```

Thread the cancel_event through to the executor. Modify the `handle_message` call:
```python
response = await agent_service.handle_message(
    msg, status_callback=send_status, stream_callback=send_chunk,
    abort_event=cancel_event,
)
```

After the response, reset:
```python
cancel_event = None
```

- [ ] **Step 3: Thread abort_event through agent_service → agent → executor**

The call chain is: `agent_service.handle_message()` → `agent.handle_message()` → `agent._run()` → `self.executor.execute()`.

The executor already accepts `abort_event` (line 84). We need to add the parameter to the three callers.

In `odigos/core/agent_service.py` line 35, add `abort_event` parameter:
```python
async def handle_message(self, message, *, status_callback=None, stream_callback=None, abort_event=None):
    return await self.agent.handle_message(
        message, status_callback=status_callback, stream_callback=stream_callback,
        abort_event=abort_event,
    )
```

In `odigos/core/agent.py` line 92, add `abort_event` to `handle_message()`:
```python
async def handle_message(self, message, *, status_callback=None, stream_callback=None, abort_event=None):
    ...
    return await self._run(
        conversation_id, message,
        status_callback=status_callback,
        context_metadata=context_metadata,
        stream_callback=stream_callback,
        abort_event=abort_event,
    )
```

In `odigos/core/agent.py` line 115, add `abort_event` to `_run()`:
```python
async def _run(self, conversation_id, message, *, status_callback=None, context_metadata=None, stream_callback=None, abort_event=None):
    ...
    result = await self.executor.execute(
        conversation_id, message.content,
        abort_event=abort_event,
        query_analysis=analysis,
        status_callback=status_callback,
        context_metadata=context_metadata,
        stream_callback=stream_callback,
    )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_cancel_ws.py -x -v`
Expected: PASS

Run: `uv run pytest tests/ -x -q --timeout=60`
Expected: All existing tests still pass

- [ ] **Step 5: Commit**

```bash
git add odigos/api/ws.py odigos/core/agent_service.py odigos/core/agent.py tests/test_cancel_ws.py
git commit -m "feat: cancel mechanism — stop button sends cancel event through to executor"
```

---

### Task 3: TTS Endpoint Fixes (auth, config voice, disabled check)

**Files:**
- Modify: `odigos/api/audio.py`
- Modify: `tests/test_audio_ws.py`

- [ ] **Step 1: Write the failing tests**

The existing `_make_app()` in `tests/test_audio_ws.py` already accepts `voice_config` (line 10). Add these tests:
```python
class TestTTSAuth:
    def test_tts_requires_auth(self):
        """TTS endpoint should require authentication."""
        app = _make_app()
        client = TestClient(app)
        resp = client.get("/api/audio/speak?text=hello")
        assert resp.status_code == 401

    def test_tts_with_auth_works(self):
        """TTS endpoint should work with valid auth."""
        app = _make_app()
        client = TestClient(app)
        resp = client.get(
            "/api/audio/speak?text=hello",
            headers={"Authorization": "Bearer test-key"},
        )
        assert resp.status_code == 200

    def test_tts_disabled_returns_404(self):
        """TTS endpoint returns 404 when tts_provider is disabled."""
        from odigos.config import VoiceConfig
        app = _make_app(voice_config=VoiceConfig(tts_provider="disabled"))
        client = TestClient(app)
        resp = client.get(
            "/api/audio/speak?text=hello",
            headers={"Authorization": "Bearer test-key"},
        )
        assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_audio_ws.py::TestTTSAuth -x -v`
Expected: FAIL (no auth on speak endpoint)

- [ ] **Step 3: Fix the speak endpoint**

In `odigos/api/audio.py`, modify the `speak` endpoint:

```python
from fastapi import Depends, Request
from odigos.api.deps import require_auth

@router.get("/audio/speak", dependencies=[Depends(require_auth)])
async def speak(text: str, request: Request):
    """Convert text to speech using edge-tts. Returns audio stream."""
    settings = request.app.state.settings
    voice_config = settings.voice

    if voice_config.tts_provider == "disabled":
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content={"detail": "TTS is disabled"})

    if not text:
        return StreamingResponse(io.BytesIO(b""), media_type="audio/mpeg")

    try:
        import edge_tts
        communicate = edge_tts.Communicate(text, voice=voice_config.tts_voice)
        audio_data = bytearray()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data.extend(chunk["data"])

        return StreamingResponse(
            io.BytesIO(bytes(audio_data)),
            media_type="audio/mpeg",
            headers={"Content-Disposition": "inline"},
        )
    except Exception as e:
        logger.warning("TTS failed: %s", e)
        return StreamingResponse(io.BytesIO(b""), media_type="audio/mpeg")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_audio_ws.py -x -v`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add odigos/api/audio.py tests/test_audio_ws.py
git commit -m "fix: add auth to TTS endpoint, read voice from config, respect disabled"
```

---

### Task 4: Concise Mode Backend

**Files:**
- Modify: `odigos/config.py` (add `concise_mode` to `AgentConfig`)
- Modify: `odigos/tools/settings_tool.py` (add to ALLOWED_KEYS)
- Modify: `odigos/personality/prompt_builder.py` (append concise instruction)
- Modify: `odigos/core/context.py` (pass settings to prompt_builder)
- Create: `tests/test_concise_mode.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_concise_mode.py
"""Tests for concise mode prompt injection."""
from odigos.personality.prompt_builder import build_system_prompt


class TestConciseMode:
    def test_concise_instruction_appended(self):
        """When concise_mode is True, the concise instruction should appear in the prompt."""
        prompt = build_system_prompt(sections=[], concise_mode=True)
        assert "Be concise" in prompt

    def test_concise_instruction_absent_by_default(self):
        """When concise_mode is False, no concise instruction."""
        prompt = build_system_prompt(sections=[], concise_mode=False)
        assert "Be concise" not in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_concise_mode.py -x -v`
Expected: FAIL (build_system_prompt doesn't accept concise_mode)

- [ ] **Step 3: Add concise_mode to AgentConfig**

In `odigos/config.py`, add to `AgentConfig`:
```python
concise_mode: bool = False
```

- [ ] **Step 4: Add to settings_tool allowed keys**

In `odigos/tools/settings_tool.py`, add to `ALLOWED_KEYS`:
```python
"agent.concise_mode",
```

- [ ] **Step 5: Add concise_mode parameter to prompt_builder**

In `odigos/personality/prompt_builder.py`, add `concise_mode: bool = False` parameter to `build_system_prompt()`:

```python
def build_system_prompt(
    sections: list[PromptSection],
    memory_context: str = "",
    memory_index: str = "",
    skill_catalog: str = "",
    corrections_context: str = "",
    doc_listing: str = "",
    agent_name: str = "",
    skill_hints: str = "",
    active_plan: str = "",
    error_hints: str = "",
    experiences: str = "",
    user_profile: str = "",
    user_facts: str = "",
    recovery_briefing: str = "",
    page_context: str = "",
    last_interaction: str = "",
    concise_mode: bool = False,
) -> str:
```

At the end of the function, before `return`, add:
```python
    if concise_mode:
        parts.append(
            "IMPORTANT: Be concise. Lead with the direct answer. "
            "Only elaborate if the user asks for more detail. "
            "Avoid restating the question, unnecessary caveats, "
            "or multi-paragraph explanations when a sentence will do."
        )
```

- [ ] **Step 6: Thread concise_mode from settings into context.py**

`ContextAssembler` is instantiated in `odigos/core/agent.py` line 63. It does not currently receive settings.

In `odigos/core/context.py` line 38, add `settings=None` to `ContextAssembler.__init__`:
```python
def __init__(
    self,
    db: Database,
    agent_name: str,
    history_limit: int = 20,
    memory_manager=None,
    sections_dir: str = "data/agent",
    summarizer=None,
    skill_registry=None,
    corrections_manager=None,
    checkpoint_manager=None,
    settings=None,
) -> None:
    ...
    self.settings = settings
```

In `odigos/core/agent.py` line 63, pass settings to the ContextAssembler constructor. The Agent `__init__` already receives a `settings` parameter (it's used for budget etc). Add:
```python
self.context_assembler = ContextAssembler(
    db,
    agent_name,
    history_limit,
    memory_manager=memory_manager,
    summarizer=summarizer,
    skill_registry=skill_registry,
    corrections_manager=corrections_manager,
    settings=settings,
)
```

In `odigos/core/context.py` at the `build_system_prompt()` call (~line 399), add:
```python
concise_mode = getattr(getattr(self.settings, 'agent', None), 'concise_mode', False) if self.settings else False

system_prompt = build_system_prompt(
    ...,
    concise_mode=concise_mode,
)
```

- [ ] **Step 7: Run tests**

Run: `uv run pytest tests/test_concise_mode.py -x -v`
Expected: PASS

Run: `uv run pytest tests/ -x -q --timeout=60`
Expected: All pass

- [ ] **Step 8: Commit**

```bash
git add odigos/config.py odigos/tools/settings_tool.py odigos/personality/prompt_builder.py odigos/core/context.py tests/test_concise_mode.py
git commit -m "feat: concise mode — user toggle reduces agent verbosity via prompt"
```

---

### Task 5: Edit/Retry WebSocket Message Handling

**Files:**
- Modify: `odigos/api/ws.py`
- Create: `tests/test_edit_retry_ws.py`

- [ ] **Step 1: Write the test**

Note: Full WebSocket integration tests require the full app stack. We test the DB truncation logic directly.

```python
# tests/test_edit_retry_ws.py
"""Tests for edit message truncation logic."""
import pytest
from odigos.db import Database


class TestEditTruncation:
    @pytest.mark.asyncio
    async def test_truncate_messages_from_index(self, tmp_path):
        """Editing a message should delete all messages from that index onward."""
        db = Database(str(tmp_path / "test.db"))
        await db.initialize()
        conv_id = "test-conv"

        # Insert 5 messages
        for i in range(5):
            await db.execute(
                "INSERT INTO messages (id, conversation_id, role, content) VALUES (?, ?, ?, ?)",
                (f"msg-{i}", conv_id, "user" if i % 2 == 0 else "assistant", f"message {i}"),
            )

        # Truncate from index 2 (delete messages 2, 3, 4)
        rows = await db.fetch_all(
            "SELECT id FROM messages WHERE conversation_id = ? ORDER BY created_at",
            (conv_id,),
        )
        ids_to_delete = [r["id"] for r in rows[2:]]
        placeholders = ",".join("?" * len(ids_to_delete))
        await db.execute(
            f"DELETE FROM messages WHERE id IN ({placeholders})",
            ids_to_delete,
        )

        remaining = await db.fetch_all(
            "SELECT id FROM messages WHERE conversation_id = ? ORDER BY created_at",
            (conv_id,),
        )
        assert len(remaining) == 2
        assert remaining[0]["id"] == "msg-0"
        assert remaining[1]["id"] == "msg-1"
```

- [ ] **Step 2: Add edit handler to ws.py**

In the main message loop, add:

```python
elif msg_type == "edit":
    # Edit user message: truncate history, re-send edited content
    edit_index = data.get("message_index")
    edit_content = data.get("content", "")
    if edit_index is not None and edit_content:
        # Truncate conversation history in DB from this index
        agent_service = websocket.app.state.agent_service
        db = agent_service.agent.db
        try:
            messages_rows = await db.fetch_all(
                "SELECT id FROM messages WHERE conversation_id = ? ORDER BY created_at",
                (conversation_id,),
            )
            # Delete messages from edit_index onwards
            if edit_index < len(messages_rows):
                ids_to_delete = [r["id"] for r in messages_rows[edit_index:]]
                placeholders = ",".join("?" * len(ids_to_delete))
                await db.execute(
                    f"DELETE FROM messages WHERE id IN ({placeholders})",
                    ids_to_delete,
                )
        except Exception as e:
            logger.warning("Edit truncation failed: %s", e)

        # Re-send as a chat message
        data["type"] = "chat"
        data["content"] = edit_content
        if not chat_queue.full():
            chat_queue.put_nowait(data)

elif msg_type == "retry":
    # Retry: re-send the last user message
    # The frontend tracks which message to retry and sends the content
    retry_content = data.get("content", "")
    if retry_content:
        data["type"] = "chat"
        data["content"] = retry_content
        if not chat_queue.full():
            chat_queue.put_nowait(data)
```

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/test_edit_retry_ws.py -x -v`
Expected: PASS

Run: `uv run pytest tests/ -x -q --timeout=60`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add odigos/api/ws.py tests/test_edit_retry_ws.py
git commit -m "feat: edit and retry WebSocket message handling"
```

---

## Chunk 2: Gemini Frontend Handoff

### Task 6: Write Gemini Handoff Document

**Files:**
- Create: `docs/GEMINI-VOICE-HANDOFF.md`

The handoff doc gives Gemini all the context it needs to implement the 7 frontend tasks without reading backend code.

- [ ] **Step 1: Write the handoff document**

```markdown
# Gemini Voice & Message Actions Handoff

## Overview
7 frontend tasks for voice mode Phase A. All backend endpoints are already implemented.
Spec: `docs/superpowers/specs/2026-03-26-voice-mode-design.md`

## API Endpoints Available

### POST /api/conversations/{conversation_id}/report
Auth: Bearer token or session cookie
Body: `{ "message_index": int, "reason": "wrong"|"unhelpful"|"harmful", "message_content": string }`
Response: `{ "status": "reported", "evaluation_id": string }`

### GET /api/audio/speak?text={text}
Auth: Bearer token or session cookie
Returns: audio/mpeg stream
Returns 404 if `voice.tts_provider === "disabled"`

### GET /api/settings
Returns `{ ..., "voice": { "stt_provider": "groq"|"local"|"disabled", "tts_provider": "edge"|"disabled", ... }, "agent": { "concise_mode": false, ... } }`

### POST /api/settings
Body includes: `{ "agent": { "concise_mode": true } }`

### WebSocket /api/ws
New message types:
- Send `{"type": "cancel"}` — stops generation. Server responds with `{"type": "stream_end", "cancelled": true}`
- Send `{"type": "edit", "message_index": N, "content": "new text"}` — truncates and re-sends
- Send `{"type": "retry", "content": "original user message"}` — re-generates response

## Tasks

### G-V1: MessageActions Component
Create `dashboard/src/components/MessageActions.tsx`

A horizontal icon bar that appears on hover below messages.

**Assistant message actions:**
- Copy (Copy icon) — `navigator.clipboard.writeText(content)`, toast "Copied"
- Speak (Volume2 icon) — calls `playTTS(stripForTTS(content))` (import from tts-filter.ts)
- Report (Flag icon) — opens small inline dropdown with options: Wrong, Unhelpful, Harmful. On select, POST to report endpoint.
- Retry (RotateCcw icon) — sends `{"type": "retry", "content": previousUserMessage}` over WebSocket. Disabled while streaming.

**User message actions:**
- Copy (Copy icon) — same as above
- Edit (Pencil icon) — makes message editable inline. On confirm, sends `{"type": "edit", "message_index": N, "content": editedText}` over WebSocket.

**Styling:**
- `opacity-0 group-hover/msg:opacity-100 transition-opacity`
- Icons: h-4 w-4, text-muted-foreground hover:text-foreground
- Gap between icons: gap-2
- Positioned below message content, left-aligned

**Props:**
```typescript
interface MessageActionsProps {
  role: 'user' | 'assistant'
  content: string
  messageIndex: number
  conversationId: string
  previousUserMessage?: string  // for retry
  isStreaming: boolean          // disable retry while streaming
  ttsAvailable: boolean        // hide speak if TTS disabled
  socket: ChatSocket | null    // ChatSocket from '@/lib/ws' — the existing WebSocket wrapper (socketRef.current)
  onEdit: (index: number, content: string) => void
  playTTS: (text: string) => void
}
```

### G-V2: TTS Filter Utility
Create `dashboard/src/lib/tts-filter.ts`

```typescript
export function stripForTTS(text: string): string
```

Rules applied in order:
1. Remove fenced code blocks (``` ... ```)
2. Remove indented code blocks (4+ spaces/tab at line start)
3. Replace URLs (https?://...) with "link"
4. Strip inline code backticks: `foo` -> foo
5. Strip markdown images: ![alt](url) -> alt
6. Strip markdown links: [text](url) -> text
7. Strip HTML tags
8. Collapse multiple newlines into single newline
9. Trim whitespace

Edge cases:
- If result is empty after filtering -> return empty string (caller skips TTS)
- If result > 2000 chars -> truncate at last sentence boundary (period/exclamation/question mark + space) before 2000, append "... and more"

Export a second helper:
```typescript
export function shouldPlayTTS(text: string): boolean
// Returns true if stripForTTS(text) is non-empty
```

### G-V3: Stop Button
Modify `dashboard/src/components/ChatPanel.tsx`

Replace the Send button with a contextual Send/Stop button:
- When `isStreaming` is false and input has text: ArrowUp icon (send)
- When `isStreaming` is true: Square icon with red accent (`text-red-500`)
- Click Stop sends `{"type": "cancel"}` via the WebSocket
- Handle `{"type": "stream_end", "cancelled": true}` to reset streaming state

Track streaming state: set true when chat message is sent, set false on `chat_response` or `stream_end`.

### G-V4: Auto-Read Toggle
Modify `dashboard/src/components/ChatPanel.tsx`

Add a toggle button in the chat header area:
- Icon: Volume2 with a small dot indicator when active
- Tooltip: "Auto-read responses"
- Persisted in `localStorage` key `odigos-auto-read`
- Only visible when `ttsAvailable` is true
- When enabled: after each `chat_response` (not `stream_end.cancelled`), call `playTTS(stripForTTS(responseContent))`

**Audio management:**
- Keep a ref to the current Audio object
- Starting new TTS stops any currently playing audio (currentAudio.pause(), currentAudio.src = "")
- Stop button also stops current audio playback

### G-V5: Fix Voice Detection
Modify `dashboard/src/components/ChatPanel.tsx`

Replace the current voice detection:
```typescript
// OLD (broken):
.then((s) => setVoiceEnabled(!!(s.stt?.enabled || s.tts?.enabled)))

// NEW:
.then((s) => {
  setSttAvailable(s.voice?.stt_provider !== 'disabled')
  setTtsAvailable(s.voice?.tts_provider !== 'disabled')
})
```

Replace single `voiceEnabled` state with two:
```typescript
const [sttAvailable, setSttAvailable] = useState(false)
const [ttsAvailable, setTtsAvailable] = useState(false)
```

Update all references:
- Mic button: visible when `sttAvailable`
- Speak/auto-read: visible when `ttsAvailable`
- MessageActions speak: gated on `ttsAvailable`

### G-V6: Concise Mode Toggle
Modify `dashboard/src/components/ChatPanel.tsx`

Add a toggle in the chat header (next to auto-read toggle):
- Icon: `AlignLeft` (lucide) — tooltip "Concise mode"
- Active state: highlighted icon
- On toggle: POST to `/api/settings` with `{ "agent": { "concise_mode": true/false } }`
- Read initial state from GET `/api/settings` response (`s.agent?.concise_mode`)
- Store in local state (not localStorage — it persists server-side)

### G-V7: ChatPanel Integration
Modify `dashboard/src/components/ChatPanel.tsx`

Wire everything together:
1. Import and render `MessageActions` on each message (replace existing single speaker button)
2. Import `stripForTTS`, `shouldPlayTTS` from `tts-filter.ts`
3. Update `playTTS` to use `stripForTTS` and manage Audio ref for stop/overlap
4. Add `isStreaming` state tracking
5. Render Stop/Send button based on streaming state
6. Render auto-read and concise toggles in header
7. Wire edit/retry through WebSocket

**Message rendering change:**
Replace the current message block (with single speaker button) with:
```tsx
<div className="group/msg w-full overflow-hidden">
  <div className="chat-text ...">
    <Markdown>{msg.content}</Markdown>
  </div>
  <MessageActions
    role={msg.role}
    content={msg.content}
    messageIndex={actualIndex}
    conversationId={activeConversationId}
    previousUserMessage={getPreviousUserMessage(actualIndex)}
    isStreaming={isStreaming}
    ttsAvailable={ttsAvailable}
    socket={socketRef.current}
    onEdit={handleEdit}
    playTTS={playTTS}
  />
</div>
```

Similarly for user messages, add MessageActions with `role="user"`.

## Icons to Import
Add to existing lucide-react imports:
```typescript
import { Copy, Flag, RotateCcw, Pencil, Square, AlignLeft, Volume2 } from 'lucide-react'
```

## Testing
- Manual test each action on both user and assistant messages
- Test stop button during streaming
- Test auto-read toggle with a short response
- Test concise mode toggle persists across page reload
- Test TTS filter with code-heavy and URL-heavy messages
- Verify mic button appears only when stt_provider is not disabled
- Verify speak/auto-read hidden when tts_provider is disabled
```

- [ ] **Step 2: Commit the handoff doc**

```bash
git add docs/GEMINI-VOICE-HANDOFF.md
git commit -m "docs: Gemini handoff for voice mode frontend tasks (G-V1 through G-V7)"
```

---

## Implementation Notes

**Dependency order:**
1. Tasks 1-5 (backend) can all be done in parallel — no dependencies between them
2. Task 6 (Gemini handoff) depends on Tasks 1-5 being committed so the APIs exist
3. Gemini tasks G-V1 through G-V7 depend on Task 6 and the backend being deployed

**What NOT to do:**
- Do not touch `plugins/stt/` or `plugins/tts/` — plugin system stays as-is
- Do not modify `VoiceConfig` in `odigos/config.py` — it's already complete. (`AgentConfig` does get a new `concise_mode` field.)
- Do not implement Phase B (VoiceOrb, input bar swap) — that's future work
- Do not add wake word support — explicitly rejected
