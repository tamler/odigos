# Voice Mode & Message Actions Design

**Date:** 2026-03-26
**Status:** Draft

## Overview

Three interconnected features that make Odigos more interactive and accessible:

1. **Message hover actions** — copy, speak, report, retry, edit on every message
2. **Voice mode Phase A** — fix existing voice, add TTS content filtering, auto-read toggle, stop button
3. **Voice mode Phase B** — conversational voice UI with input-bar orb swap

## 1. Message Hover Actions

### Assistant Messages

A horizontal icon bar appears on hover (`opacity-0 group-hover:opacity-100`), positioned below the message content:

| Action | Icon | Behavior |
|--------|------|----------|
| **Copy** | `Copy` | Copies raw markdown to clipboard. Toast: "Copied to clipboard" |
| **Speak** | `Volume2` | Reads message aloud via edge-tts (filtered, see Section 3). Always available (free). |
| **Report** | `Flag` | Opens a small inline dropdown: Wrong / Unhelpful / Harmful. Sends to backend. |
| **Retry** | `RotateCcw` | Re-sends the preceding user message, regenerates this response. Replaces current assistant message with new response. Disabled while agent is streaming — user must stop first, then retry. |

### User Messages

| Action | Icon | Behavior |
|--------|------|----------|
| **Copy** | `Copy` | Copies raw text to clipboard. |
| **Edit** | `Pencil` | Makes message editable inline. On confirm (Enter or check button): sends edited message with `{"type": "edit", "message_index": N, "content": "..."}` over WebSocket. Backend truncates stored history from that index, then processes the edited text as a new message. |

### Backend: Report Endpoint

```
POST /api/conversations/{conversation_id}/report
Body: { "message_index": int, "reason": "wrong" | "unhelpful" | "harmful", "message_content": string }
```

Creates an evaluation record in the database with a negative signal:
- Stores in `evaluations` table with `source = "user_report"`, `score = -1.0`
- Includes the reason and message content for AREW analysis
- The strategist can aggregate these reports in its summary

No new database tables needed — reuses existing `evaluations` table.

Endpoint lives in a new `odigos/api/report.py` with its own router mounted under `/api/conversations`.

## 2. Stop Button

### Text Mode

The Send button (ArrowUp icon) contextually transforms while the agent is responding:

- **Idle** — Send button (ArrowUp), enabled when input has text
- **Agent responding** — Stop button (Square icon), red accent. Same position, same size.
- **Click Stop** — sends `{"type": "cancel"}` over the chat WebSocket

### Voice Mode

The orb itself is the stop control:
- Tap while agent is speaking → stops TTS playback + cancels generation
- Tap while STT is processing → cancels transcription, returns to idle
- Visual feedback: brief red flash on stop

### Backend: Cancel Mechanism

1. Client sends `{"type": "cancel"}` on the chat WebSocket
2. WebSocket handler sets a `cancel_event` (asyncio.Event) on the active request
3. The executor's streaming callback checks `cancel_event.is_set()` between chunks
4. If set, raises `CancelledError` — executor saves partial response as-is
5. WebSocket sends `{"type": "stream_end", "cancelled": true}` to confirm

Changes needed:
- `ws.py`: Handle `"cancel"` message type, maintain a per-connection `cancel_event`
- `executor.py`: Accept optional cancel event, check in stream callback
- Frontend: Send cancel message, handle `cancelled` flag in stream_end

## 3. TTS Content Filtering

A `stripForTTS(text: string): string` utility (frontend) that cleans markdown before sending to the speak endpoint:

### Rules (applied in order)

1. Remove fenced code blocks: `` ```...``` `` → removed entirely
2. Remove indented code blocks (4+ spaces or tab at line start) → removed
3. Replace URLs (`https?://...`) → "link"
4. Strip inline code backticks: `` `foo` `` → "foo"
5. Strip markdown images: `![alt](url)` → "alt" (keep alt text)
6. Strip markdown links: `[text](url)` → "text" (keep link text)
7. Strip HTML tags
8. Collapse multiple newlines into single newline
9. Trim whitespace

### Edge Cases

- If result is empty after filtering (message was entirely code/URLs) → skip TTS, no audio
- Very long messages (>2000 chars after filtering) → truncate at sentence boundary, append "... and more"
- Messages with mixed content: natural language parts read, code parts silently skipped
- Starting new TTS playback stops any currently playing audio (no concurrent playback)

### Integration Note

The existing `playTTS(msg.content)` call in ChatPanel must be updated to `playTTS(stripForTTS(msg.content))`.

### Implementation

Frontend utility in `dashboard/src/lib/tts-filter.ts`. Used by both manual speak and auto-read.

## 4. Voice Mode Phase A (Now)

### Fix Voice Detection

Current broken check:
```typescript
s.stt?.enabled || s.tts?.enabled  // old config, removed
```

New logic:
```typescript
// STT available (mic button): check voice.stt_provider !== "disabled"
const sttAvailable = s.voice?.stt_provider !== 'disabled'
// TTS always available (edge-tts is free), no check needed
```

- **Speak icon on messages**: Always visible on hover (no config gate). Free.
- **Mic button**: Visible when `stt_provider !== "disabled"` (requires Groq key or local provider).

### Auto-Read Toggle

- Small toggle button in chat header area (next to conversation title or settings)
- Icon: `Volume2` with a small indicator dot when active
- When enabled: every new assistant message auto-plays through TTS after streaming completes
- Uses `stripForTTS()` filtering
- Persisted in `localStorage` key `odigos-auto-read`
- Respects the stop button — stopping generation also prevents auto-read of partial response

### Audio WebSocket Auth

Already fixed in backend (session cookie support). Frontend needs to include credentials:
```typescript
// WebSocket inherits cookies automatically for same-origin
// No additional changes needed for cookie auth
```

But the query param token fallback needs the API key. For voice mode, cookies are the primary path.

## 5. Voice Mode Phase B (Later)

### Input Bar Swap

A toggle button (mic icon) in the input area. Clicking it:

1. Text input bar slides out (CSS transition)
2. Voice orb slides in (same space, same height allocation)
3. Rest of layout unchanged — chat messages above, artifacts panel to the side
4. Orb is the sole interaction point for voice

```
┌──────────────────────────────────────────────────┐
│                                                  │
│  Chat messages (scrolling, same as always)       │
│  - hover actions on each message                 │
│  - text streams in during agent response         │
│                                                  │
├──────────────────────────────────────────────────┤
│         ( ○ )  ← voice orb, centered             │
│    [exit voice]                                  │
└──────────────────────────────────────────────────┘
```

Can coexist with artifacts panel open to the right — voice-chat while viewing/editing a journal.

### Orb Visual States

| State | Visual | Description |
|-------|--------|-------------|
| **Idle / Listening** | Subtle breathing pulse | Waiting for user to speak |
| **User speaking** | Waveform / amplitude rings | Responding to mic input volume |
| **Processing (STT)** | Spinning dots or ring | Audio sent to Groq, waiting for transcription |
| **Agent thinking** | Pulsing glow | LLM generating response |
| **Agent speaking (TTS)** | Rhythmic pulse synced to audio | edge-tts playing response |
| **Stopped** | Brief red flash → back to idle | User tapped to cancel |

### Conversation Flow

1. User taps orb to enter voice mode (or toggle button)
2. MediaRecorder starts capturing audio
3. User speaks → orb shows amplitude visualization
4. User pauses → after silence threshold (~1.5s, tunable frontend constant `SILENCE_TIMEOUT_MS`), audio sent to Groq STT WebSocket
5. Transcribed text appears in chat as user message (auto-sent, no confirmation)
6. Agent processes → text streams into chat
7. On stream complete → auto-read via TTS (filtered)
8. TTS finishes → orb returns to listening state (step 2)
9. User taps orb to exit → returns to text input

### Interrupt Behavior

- Tap orb during TTS playback → stops audio, stops generation, returns to listening
- Tap orb during STT processing → cancels, returns to listening
- Text appears regardless of voice state — the conversation is always visible

### Exit Voice Mode

- Tap "exit voice" text link below orb
- Or tap the toggle button again
- Or press Escape
- Returns to text input bar with full input history preserved

## 6. VoiceConfig (Already Exists)

```python
class VoiceConfig(BaseModel):
    stt_provider: str = "groq"      # "groq", "local", or "disabled"
    tts_provider: str = "edge"      # "edge", "local", or "disabled"
    tts_voice: str = "en-US-AriaNeural"
    groq_model: str = "whisper-large-v3-turbo"
```

No changes needed. The agent can change voice settings via `manage_settings` tool (keys: `voice.stt_provider`, `voice.tts_provider`, `voice.tts_voice`, `voice.groq_model`).

## 7. Cost Analysis

| Component | Cost | Notes |
|-----------|------|-------|
| TTS (edge-tts) | Free | Microsoft Edge cloud service, no API key |
| STT (Groq Whisper) | ~$0.04/hr | Only when mic is active |
| Report endpoint | Free | Just a DB write |
| Cancel mechanism | Saves money | Stops LLM generation early |

A typical voice session (10 min) costs ~$0.007. Auto-read is free regardless of usage.

## 8. Files to Create/Modify

### New Files
- `dashboard/src/lib/tts-filter.ts` — TTS content filtering utility
- `dashboard/src/components/VoiceOrb.tsx` — Voice mode orb component (Phase B)
- `dashboard/src/components/MessageActions.tsx` — Hover action bar component

### Modified Files
- `dashboard/src/components/ChatPanel.tsx` — integrate message actions, fix voice check, auto-read toggle, stop button, voice mode toggle (Phase B)
- `odigos/api/ws.py` — handle cancel message type, cancel_event plumbing
- `odigos/api/settings.py` — add report endpoint (or new file `odigos/api/report.py`)
- `odigos/core/executor.py` — accept cancel event in streaming

- `odigos/api/audio.py` — fix hardcoded voice: read `tts_voice` from `request.app.state.settings.voice.tts_voice` instead of hardcoded `"en-US-AriaNeural"`. TTS speak endpoint is intentionally unauthenticated (free service, low abuse risk, used by frontend directly).
- `odigos/api/report.py` — new file for report endpoint

### Unchanged
- `odigos/config.py` — VoiceConfig already complete
- `plugins/stt/`, `plugins/tts/` — untouched, plugin system stays

## 9. Implementation Order

### Phase A (immediate)
1. `MessageActions` component with copy, speak, report, retry, edit
2. Report backend endpoint
3. `tts-filter.ts` utility
4. Fix voice detection in ChatPanel
5. Stop button (Send ↔ Stop swap) + backend cancel mechanism
6. Auto-read toggle
7. Integration testing

### Phase B (future)
1. `VoiceOrb` component with visual states
2. Input bar swap animation
3. Continuous voice conversation loop
4. Silence detection / auto-send
5. Interrupt handling
6. Polish and edge cases
