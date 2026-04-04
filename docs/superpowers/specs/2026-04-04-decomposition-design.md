# Phase 2: Large File Decomposition Design

**Date:** 2026-04-04
**Status:** Approved
**Goal:** Decompose the 4 largest files in the codebase into focused modules without changing behavior.

## Context

Four files exceed 600 lines and mix multiple concerns:
- `odigos/core/heartbeat.py` (1481 lines) — 15+ autonomous background tasks in one class
- `dashboard/src/components/ChatPanel.tsx` (783 lines) — message display, input, voice, artifacts all inline
- `dashboard/src/layouts/AppLayout.tsx` (693 lines) — sidebar, WebSocket, keyboard, conversation CRUD inline
- `dashboard/src/components/kanban.tsx` (930 lines) — **excluded**: already 16 well-decomposed exported primitives

## Decisions

| Question | Decision | Rationale |
|----------|----------|-----------|
| Heartbeat strategy | Method extraction to modules, not service classes | File size is the problem, not architecture. Methods are already well-isolated. Functions receive `self` and can be wrapped into classes later. |
| Frontend strategy | Component extraction + custom hooks | Props-down pattern. No new stores or state management changes. |
| kanban.tsx | Excluded from scope | Already well-decomposed: 16 exported primitive components, clean DnD library. |

## Design

### 1. Backend: Heartbeat Decomposition

**Current:** `odigos/core/heartbeat.py` — 1 file, 1481 lines, 1 class with 25+ methods.

**After:** Package with thin orchestrator + 7 focused modules.

```
odigos/core/heartbeat/
├── __init__.py          — re-exports Heartbeat class
├── orchestrator.py      — Heartbeat class: __init__, start, stop, _loop, _tick (~260 lines)
├── scheduled.py         — briefing, scheduled tasks, legacy reminders, recurrence utils
├── todos.py             — todo fetching and execution
├── plans.py             — multi-step plan execution with retry state
├── peers.py             — peer messaging, subagent dispatch/delivery, peer maintenance
├── idle.py              — idle thinking and goal review
├── profiling.py         — dream analysis, experience extraction, plan outcome evaluation
├── maintenance.py       — evolution, updates, storage quota, email, nudges, followups, cron
└── utils.py             — _send_notification, _log_heartbeat_session
```

#### Module breakdown:

**`orchestrator.py`** (~260 lines)
- `Heartbeat.__init__()` — all state initialization, injected dependencies
- `start()`, `stop()`, `_loop()` — lifecycle management
- `_tick()` — the phase orchestrator (unchanged logic, same `did_work` accumulator and budget gating)
- Imports functions from other modules, calls them passing `self`

**`scheduled.py`** (~120 lines)
- `maybe_send_briefing(self)` — one-time morning briefing
- `process_scheduled_tasks(self)` — unified scheduler execution
- `fire_reminders(self)` — legacy reminders table
- `reinsert_recurring_reminder(self, ...)` — re-schedule recurring
- `parse_recurrence_seconds(text)` — standalone utility

**`todos.py`** (~60 lines)
- `work_todos(self)` — fetch pending todos
- `execute_todo(self, todo)` — execute via agent, update goal_store

**`plans.py`** (~110 lines)
- `work_in_progress_plans(self)` — execute next step of active plans
- Plan retry constants (`MAX_PLAN_RETRIES`, `FAIL_MARKERS`)

**`peers.py`** (~170 lines)
- `dispatch_as_subagent(self, ...)` — spawn internal subagent
- `process_peer_messages(self)` — handle inbound peer messages with injection scanning
- `deliver_subagent_results(self)` — deliver completed results
- `peer_maintenance(self)` — announce, flush outbox, mark stale

**`idle.py`** (~80 lines)
- `idle_think(self)` — autonomous goal review during idle time
- `process_idle_response(self, response)` — parse and act on idle-think output

**`profiling.py`** (~280 lines)
- `dream_analyze_user(self)` — conversation analysis and user profile updates
- `extract_experiences(self)` — learn from tool interactions
- `evaluate_plan_outcomes(self)` — score completed plans

**`maintenance.py`** (~230 lines)
- `run_evolution(self)` — self-improvement cycle
- `check_for_updates(self)` — auto-update check and application
- `check_storage_quota(self)` — disk usage monitoring
- `check_email(self)` — inbox check
- `send_nudges(self)` — stale task notifications
- `check_followups(self)` — untracked commitment check
- `run_cron_jobs(self)` — legacy cron execution

**`utils.py`** (~30 lines)
- `send_notification(self, conversation_id, text)` — channel routing
- `log_heartbeat_session(self, ...)` — persist autonomous work

#### Pattern for module functions:

```python
# odigos/core/heartbeat/todos.py
async def work_todos(hb) -> bool:
    """Fetch and execute pending todos. Returns True if work was done."""
    rows = await hb.db.fetch_all(...)
    did_work = False
    for todo in rows[:hb._max_todos_per_tick]:
        did_work = True
        await execute_todo(hb, todo)
    return did_work

async def execute_todo(hb, todo: dict) -> None:
    """Execute a single todo via the agent."""
    ...
```

The orchestrator calls: `did_work |= await todos.work_todos(self)`

#### State ownership:

All tick counters, throttle timestamps, and configuration stay on the `Heartbeat` class in `orchestrator.py`. Module functions access them via the `hb` parameter (the Heartbeat instance).

#### Import changes for consumers:

```python
# Before:
from odigos.core.heartbeat import Heartbeat

# After (same, via __init__.py re-export):
from odigos.core.heartbeat import Heartbeat
```

No changes to bootstrap, container, or any other file that imports Heartbeat.

---

### 2. Frontend: ChatPanel Decomposition

**Current:** `dashboard/src/components/ChatPanel.tsx` — 783 lines.

**After:**

```
dashboard/src/components/
├── ChatPanel.tsx              — Orchestrator: state, effects, layout shell (~200 lines)
├── chat/
│   ├── MessageDisplay.tsx     — Message list, streaming, thinking indicator (~180 lines)
│   ├── ChatInputArea.tsx      — Textarea, file queue, action buttons (~160 lines)
│   ├── SuggestedActions.tsx   — Actions bar with expand/collapse (~45 lines)
│   ├── ArtifactGallery.tsx    — Artifact cards (ImageArtifact, AudioArtifact) (~80 lines)
│   ├── WelcomeView.tsx        — Empty state with suggested prompts (~40 lines)
│   └── VoiceModePanel.tsx     — Voice mode overlay (~20 lines)
```

#### Component responsibilities:

**`ChatPanel.tsx`** (~200 lines)
- Owns all state (13 `useState`, 4 `useRef`)
- Owns effects (conversation loading, localStorage sync, artifact fetching)
- Owns handlers (`handleSend`, `handleEdit`, `handleFilesAdded`, `handleKeyDown`)
- Renders layout shell: `<MessageDisplay>`, `<SuggestedActions>`, `<ChatInputArea>`
- Passes props to children

**`MessageDisplay.tsx`** (~180 lines)
- Props: `messages`, `streamingContent`, `thinking`, `artifacts`, `messageDisplayLimit`, `switchingConversation`, `voiceMode`, `voiceAmplitude`, `onLoadMore`, `onEdit`, `onOpenArtifact`
- Renders: message list with history pagination, streaming content, thinking indicator
- Contains: `<VoiceModePanel>` (conditional), `<ArtifactGallery>` (conditional), `<WelcomeView>` (conditional)

**`ChatInputArea.tsx`** (~160 lines)
- Props: `inputValue`, `setInputValue`, `pendingFiles`, `onSend`, `onFilesAdded`, `onRemoveFile`, `onKeyDown`, `sttAvailable`, `ttsAvailable`, `useCamera`, `setUseCamera`, `voiceMode`, `textareaRef`
- Renders: file pending display, navigation breadcrumbs, textarea with auto-height, action buttons

**`SuggestedActions.tsx`** (~45 lines)
- Props: `actions`, `showAll`, `onToggleShowAll`, `onSelect`
- Pure presentational component

**`ArtifactGallery.tsx`** (~80 lines)
- Props: `artifacts`, `onOpenArtifact`
- Contains `ImageArtifact` and `AudioArtifact` as local components (moved from ChatPanel inline)

**`WelcomeView.tsx`** (~40 lines)
- Props: `onSuggestedPrompt`
- Pure presentational, moved from inline definition

**`VoiceModePanel.tsx`** (~20 lines)
- Props: `messages`, `amplitude`, `voiceMode`
- Voice orb and reduced message display

---

### 3. Frontend: AppLayout Decomposition

**Current:** `dashboard/src/layouts/AppLayout.tsx` — 693 lines.

**After:**

```
dashboard/src/layouts/
├── AppLayout.tsx              — Layout shell: renders sidebar, outlet, panels (~200 lines)
├── AppSidebar.tsx             — Navigation sidebar (~200 lines, moved from inline memo)
├── hooks/
│   ├── useWebSocketHandler.ts — WebSocket connection + message routing (~100 lines)
│   ├── useConversationActions.ts — CRUD handlers for conversations (~80 lines)
│   ├── useRouteState.ts       — Route detection boolean flags (~20 lines)
│   └── useKeyboardShortcuts.ts — Global keyboard shortcuts (~30 lines)
```

#### Hook contracts:

**`useWebSocketHandler()`** (~100 lines)
```typescript
function useWebSocketHandler(): {
  socketRef: React.MutableRefObject<WebSocket | null>;
  connected: boolean;
}
```
- Encapsulates the 95-line WebSocket message routing (`notification`, `chat_chunk`, `chat_response`, `stream_end`, `queue_update`, `title_updated`, etc.)
- Reads/writes Zustand stores directly (same as today, just in a hook)
- Manages connection lifecycle (open, close, reconnect)

**`useConversationActions()`** (~80 lines)
```typescript
function useConversationActions(): {
  handleNewChat: () => void;
  handleSelectConversation: (id: string) => void;
  handleSelectImage: (id: string) => void;
  startRename: (id: string, title: string) => void;
  confirmRename: () => void;
  handleDelete: (id: string) => void;
  handleExport: (id: string, format: string) => void;
  displayTitle: (conv: Conversation) => string;
  editingId: string | null;
  editTitle: string;
  setEditTitle: (title: string) => void;
  editInputRef: React.RefObject<HTMLInputElement>;
}
```
- Owns the rename state (`editingId`, `editTitle`, `editInputRef`)
- Wraps all 6 conversation CRUD handlers
- Uses `useNavigate`, `useChatStore`, `useConversationStore`

**`useRouteState()`** (~20 lines)
```typescript
function useRouteState(): {
  isSettings: boolean;
  isNotebook: boolean;
  isKanban: boolean;
  isImages: boolean;
}
```
- Reads `useLocation().pathname`
- Replaces 4 inline boolean checks repeated throughout the file

**`useKeyboardShortcuts(callbacks)`** (~30 lines)
```typescript
function useKeyboardShortcuts(callbacks: {
  onNewChat: () => void;
  onSwitcher: () => void;
}): void
```
- Registers global `keydown` listener
- Handles Cmd+K (switcher), Cmd+N (new chat), Escape (close panels)

**`AppSidebar.tsx`** (~200 lines)
- Same code as the current memoized `AppSidebar` component
- Same props interface (12 callbacks + 2 booleans)
- No logic changes, just moved to own file

**`AppLayout.tsx`** (~200 lines)
- Imports hooks and sidebar
- Calls hooks, destructures returns
- Renders: QuickSwitcher, mobile menu, AppSidebar, Outlet, ChatPanel, ArtifactPreview

## File Change Summary

### Backend (heartbeat)

| File | Change |
|------|--------|
| `odigos/core/heartbeat.py` | **Deleted** — replaced by package |
| `odigos/core/heartbeat/__init__.py` | **New** — re-exports Heartbeat |
| `odigos/core/heartbeat/orchestrator.py` | **New** — Heartbeat class with lifecycle + _tick |
| `odigos/core/heartbeat/scheduled.py` | **New** — briefing, scheduled tasks, reminders |
| `odigos/core/heartbeat/todos.py` | **New** — todo execution |
| `odigos/core/heartbeat/plans.py` | **New** — plan execution |
| `odigos/core/heartbeat/peers.py` | **New** — peer messaging and subagents |
| `odigos/core/heartbeat/idle.py` | **New** — idle thinking |
| `odigos/core/heartbeat/profiling.py` | **New** — user profiling and experience extraction |
| `odigos/core/heartbeat/maintenance.py` | **New** — evolution, updates, email, nudges, cron |
| `odigos/core/heartbeat/utils.py` | **New** — shared utilities |

### Frontend (ChatPanel)

| File | Change |
|------|--------|
| `dashboard/src/components/ChatPanel.tsx` | **Slimmed** — orchestrator only (~200 lines) |
| `dashboard/src/components/chat/MessageDisplay.tsx` | **New** |
| `dashboard/src/components/chat/ChatInputArea.tsx` | **New** |
| `dashboard/src/components/chat/SuggestedActions.tsx` | **New** |
| `dashboard/src/components/chat/ArtifactGallery.tsx` | **New** |
| `dashboard/src/components/chat/WelcomeView.tsx` | **New** |
| `dashboard/src/components/chat/VoiceModePanel.tsx` | **New** |

### Frontend (AppLayout)

| File | Change |
|------|--------|
| `dashboard/src/layouts/AppLayout.tsx` | **Slimmed** — layout shell only (~200 lines) |
| `dashboard/src/layouts/AppSidebar.tsx` | **New** — moved from inline |
| `dashboard/src/layouts/hooks/useWebSocketHandler.ts` | **New** |
| `dashboard/src/layouts/hooks/useConversationActions.ts` | **New** |
| `dashboard/src/layouts/hooks/useRouteState.ts` | **New** |
| `dashboard/src/layouts/hooks/useKeyboardShortcuts.ts` | **New** |

## What This Does NOT Change

- No behavior changes — pure structural refactor
- No new dependencies
- No API changes
- No Zustand store changes
- No route changes
- `from odigos.core.heartbeat import Heartbeat` still works (re-export)
- All existing tests pass without modification
- kanban.tsx is untouched (already well-decomposed)
