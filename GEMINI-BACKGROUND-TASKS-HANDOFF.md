# Gemini Frontend Handoff: Background Tasks & System Messages

## Context

The backend now supports **backgroundable tools** — image generation and music generation return immediately with a "pending" status instead of blocking for 2-3 minutes. The heartbeat polls in the background and delivers results via WebSocket.

**What the backend does:**
1. Tool returns `status="pending"` → executor stores task in `tasks` table
2. Heartbeat polls every 30s → when done, downloads artifact, stores in DB
3. Heartbeat sends WebSocket message: `{"type": "task_completed", "tool_name": "...", "result": "...", "artifact": {...}}`
4. Heartbeat injects a system message into the conversation: `[Background task completed] Image generated: sunset.png (1.2MB)`
5. Heartbeat sends notification via the notifier (toast already partially wired)

**What the frontend needs:**
1. A background task indicator showing active tasks
2. Proper rendering of system messages in the chat
3. WebSocket handler update for task lifecycle events

---

## File Map (What Changed on Backend)

These are the files that matter for understanding the data flow:

| Backend File | What It Does |
|-------------|-------------|
| `odigos/core/heartbeat/background.py` | Polls pending tasks, sends `task_completed` WebSocket event |
| `odigos/core/executor.py` | Detects `status="pending"`, stores in `tasks` table |
| `odigos/tools/image_gen.py` | Returns `status="pending"` immediately, `complete_background()` for polling |
| `odigos/tools/music_gen.py` | Same pattern |

## Frontend Files to Modify

| File | Change |
|------|--------|
| `dashboard/src/stores/uiStore.ts` | Add `backgroundTasks` state array |
| `dashboard/src/layouts/hooks/useWebSocketHandler.ts` | Handle `task_completed` + new `task_started` tracking |
| `dashboard/src/components/chat/ChatInputArea.tsx` | Show background task indicator near input |
| `dashboard/src/components/chat/MessageDisplay.tsx` | Render system messages with distinct style |

---

## Task G-BG1: Background Tasks State in uiStore

**Priority:** Medium

Add background task tracking to the UI store.

**File:** `dashboard/src/stores/uiStore.ts`

Add to the store:

```typescript
interface BackgroundTask {
  id: string
  toolName: string
  description: string
  startedAt: string
  conversationId: string
}

// In the store state:
backgroundTasks: BackgroundTask[]
addBackgroundTask: (task: BackgroundTask) => void
removeBackgroundTask: (id: string) => void
clearBackgroundTasks: () => void
```

Implementation:

```typescript
backgroundTasks: [],
addBackgroundTask: (task) => set((s) => ({
  backgroundTasks: [...s.backgroundTasks, task]
})),
removeBackgroundTask: (id) => set((s) => ({
  backgroundTasks: s.backgroundTasks.filter(t => t.id !== id)
})),
clearBackgroundTasks: () => set({ backgroundTasks: [] }),
```

---

## Task G-BG2: WebSocket Handler Updates

**Priority:** Medium

The WebSocket handler already has a basic `task_completed` handler. It needs to be enhanced, and a `task_started` flow needs to be added.

**File:** `dashboard/src/layouts/hooks/useWebSocketHandler.ts`

**Currently (around line 105-106):**
```typescript
if (msg.type === 'task_completed')
    toast.success(`Completed: ${msg.task || 'Background task'}`, { duration: 3000 })
```

**Replace with:**

```typescript
if (msg.type === 'task_completed') {
  const { removeBackgroundTask } = useUIStore.getState()
  removeBackgroundTask(msg.task_id)

  // Show toast with artifact info if available
  const toolLabel = msg.tool_name?.replace('generate_', '') || 'Task'
  toast.success(`${toolLabel} complete: ${msg.result || 'Ready'}`, { duration: 5000 })

  // If we're in the same conversation, the system message will appear in chat
  // If not, the toast is the notification
}
```

**For tracking when tasks start**, the agent's response to a `status="pending"` tool will include text like "Image generation started..." The backend doesn't send a separate `task_started` WebSocket event. Instead, track it from the chat response:

When the agent's response contains text about starting a background task, the `chat_response` handler can detect it. Alternatively, add tracking when the executor stores the task (requires a new WebSocket event type from backend — optional enhancement).

**Simpler approach:** The `status` WebSocket messages already show tool progress ("Generating image..."). Use these as the indicator:

```typescript
if (msg.type === 'status') {
  // If status mentions a generating/processing tool, show as background task
  const { setStatus } = useUIStore.getState()
  setStatus(msg.text)
}
```

---

## Task G-BG3: Background Task Indicator

**Priority:** Medium

Show a subtle, non-intrusive indicator near the chat input when background tasks are running. This could be:
- A scrolling text line above the input: "Generating image... Composing music..."
- A small pill/badge in the input area
- Part of the existing loading/status text area

**File:** `dashboard/src/components/chat/ChatInputArea.tsx`

**Design guidance:**
- Only show when `backgroundTasks.length > 0`
- Animate subtly (pulse, shimmer, or scrolling text)
- Clicking could expand to show task list (optional, not required)
- Should not obscure the input or interrupt typing
- Use existing Tailwind animation utilities

**Example implementation:**

```tsx
import { useUIStore } from '@/stores/uiStore'

function BackgroundTaskIndicator() {
  const tasks = useUIStore(s => s.backgroundTasks)
  if (tasks.length === 0) return null

  return (
    <div className="flex items-center gap-2 px-3 py-1.5 text-xs text-muted-foreground animate-pulse">
      <div className="h-1.5 w-1.5 rounded-full bg-blue-500 animate-pulse" />
      {tasks.length === 1
        ? `${tasks[0].description}...`
        : `${tasks.length} tasks running...`
      }
    </div>
  )
}
```

Place it above the textarea in `ChatInputArea.tsx`, or integrate it into the existing status/loading area.

---

## Task G-BG4: System Message Rendering

**Priority:** High — this is needed for background task results to appear in chat

The backend now injects system messages into conversations with `role="system"` and content prefixed with `[Background task completed]`. These need to render distinctly from user and assistant messages.

**File:** `dashboard/src/components/chat/MessageDisplay.tsx`

**Current state:** System messages may not render at all, or render as plain text indistinguishable from assistant messages.

**Required behavior:**
- System messages with `[Background task completed]` prefix should render as a compact notification card
- Show: tool icon (image/music), result text, artifact link if available
- Visually distinct: muted background, smaller text, no avatar
- Should NOT look like the agent "said" something — it's a notification, not a conversation turn

**Example styling:**

```tsx
function SystemMessage({ content }: { content: string }) {
  const isBackgroundResult = content.startsWith('[Background task completed]')
  const displayText = content.replace('[Background task completed] ', '')

  return (
    <div className="flex justify-center my-2">
      <div className="inline-flex items-center gap-2 rounded-full bg-muted/50 px-4 py-1.5 text-xs text-muted-foreground">
        {isBackgroundResult && <CheckCircle2 className="h-3.5 w-3.5 text-green-500" />}
        <span>{displayText}</span>
      </div>
    </div>
  )
}
```

In the message list rendering loop, check for `role === 'system'`:

```tsx
{messages.map(msg => {
  if (msg.role === 'system') return <SystemMessage key={msg.id} content={msg.content} />
  // ... existing user/assistant rendering
})}
```

---

## Task G-BG5: Artifact Card for Completed Background Tasks

**Priority:** Low (enhancement)

When a background image/music task completes and the artifact appears in the conversation, it should render as an interactive card (image thumbnail, audio player) — not just text.

**This may already work** if the artifact is added to the artifacts array and the existing `ArtifactGallery` component renders it. Check:

1. Does the heartbeat's system message injection also add the artifact to the artifacts table? (Yes — `background.py` stores it via `complete_background()`)
2. Does the frontend fetch artifacts for the conversation? (Should — check if `fetchArtifacts` is called on conversation load)
3. Does `ArtifactGallery` render artifacts from the store?

If artifacts already appear when the conversation is refreshed, this task is just ensuring they appear immediately (without refresh) — which the `task_completed` WebSocket event enables.

---

## Data Flow Summary

```
User: "Generate an image of a sunset"
  ↓
Agent calls generate_image → returns immediately with "I've started generating..."
  ↓
User sees: agent message "Image generation started. I'll notify you when it's ready."
  ↓
[User continues chatting normally]
  ↓
[30 seconds later, heartbeat polls]
  ↓
Heartbeat: image done → downloads → stores artifact → injects system message
  ↓
WebSocket: { type: "task_completed", tool_name: "generate_image", result: "Image generated: sunset.png" }
  ↓
Frontend: toast notification + system message appears in chat + artifact card
```

## WebSocket Message Shape

```typescript
// Sent by heartbeat when a background task completes
interface TaskCompletedMessage {
  type: 'task_completed'
  task_id: string           // Internal task ID
  tool_name: string         // "generate_image" | "generate_music"
  conversation_id: string   // Which conversation this belongs to
  result: string            // Human-readable result text
  artifact: {               // null if no artifact
    id: string
    filename: string
    content_type: string    // "image/png" | "audio/mpeg"
    file_size: number
    download_url: string    // "/api/artifacts/{id}/download"
  } | null
}
```

## Notes

- The backend changes are already merged and pushed to main
- All 95 backend tests pass
- The `task_completed` WebSocket message type was already partially handled in the frontend (basic toast) — enhance it
- System messages in the DB have `role='system'` — check how the frontend currently filters/renders messages by role
- The `backgroundTasks` store state is ephemeral — cleared on page reload. The backend `tasks` table is the source of truth for persistent state.
