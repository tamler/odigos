# Phase 2: Large File Decomposition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decompose heartbeat.py (1481 lines), ChatPanel.tsx (783 lines), and AppLayout.tsx (693 lines) into focused modules without changing behavior.

**Architecture:** Backend: convert heartbeat.py to a package with thin orchestrator + 7 focused modules using function extraction (functions receive `self`). Frontend: extract components from ChatPanel into `chat/` subdirectory, extract custom hooks and sidebar from AppLayout into `hooks/` subdirectory.

**Tech Stack:** Python 3.12, React 19, TypeScript, pytest

**Spec:** `docs/superpowers/specs/2026-04-04-decomposition-design.md`

---

## File Structure

### Backend

| File | Responsibility |
|------|---------------|
| `odigos/core/heartbeat/__init__.py` | Re-export Heartbeat class |
| `odigos/core/heartbeat/orchestrator.py` | Heartbeat class: __init__, start, stop, _loop, _tick |
| `odigos/core/heartbeat/scheduled.py` | Briefing, scheduled tasks, legacy reminders, recurrence |
| `odigos/core/heartbeat/todos.py` | Todo fetching and execution |
| `odigos/core/heartbeat/plans.py` | Multi-step plan execution with retry |
| `odigos/core/heartbeat/peers.py` | Peer messaging, subagent dispatch/delivery, maintenance |
| `odigos/core/heartbeat/idle.py` | Idle thinking and goal review |
| `odigos/core/heartbeat/profiling.py` | Dream analysis, experience extraction, outcome evaluation |
| `odigos/core/heartbeat/maintenance.py` | Evolution, updates, storage, email, nudges, followups, cron |
| `odigos/core/heartbeat/utils.py` | send_notification, log_heartbeat_session |

### Frontend — ChatPanel

| File | Responsibility |
|------|---------------|
| `dashboard/src/components/ChatPanel.tsx` | Slimmed orchestrator (~200 lines) |
| `dashboard/src/components/chat/WelcomeView.tsx` | Empty state with suggested prompts |
| `dashboard/src/components/chat/ArtifactGallery.tsx` | Artifact cards (image, audio) |
| `dashboard/src/components/chat/VoiceModePanel.tsx` | Voice mode overlay |
| `dashboard/src/components/chat/SuggestedActions.tsx` | Suggested actions bar |
| `dashboard/src/components/chat/MessageDisplay.tsx` | Message list, streaming, thinking |
| `dashboard/src/components/chat/ChatInputArea.tsx` | Textarea, file queue, action buttons |

### Frontend — AppLayout

| File | Responsibility |
|------|---------------|
| `dashboard/src/layouts/AppLayout.tsx` | Slimmed layout shell (~200 lines) |
| `dashboard/src/layouts/AppSidebar.tsx` | Navigation sidebar (moved from inline) |
| `dashboard/src/layouts/hooks/useRouteState.ts` | Route detection flags |
| `dashboard/src/layouts/hooks/useKeyboardShortcuts.ts` | Global keyboard shortcuts |
| `dashboard/src/layouts/hooks/useConversationActions.ts` | Conversation CRUD handlers |
| `dashboard/src/layouts/hooks/useWebSocketHandler.ts` | WebSocket connection + message routing |

---

### Task 1: Create heartbeat package with utils module

This task converts `heartbeat.py` from a single file to a package. We start by creating the package structure and extracting the utility functions that other modules will depend on.

**Files:**
- Create: `odigos/core/heartbeat/__init__.py`
- Create: `odigos/core/heartbeat/utils.py`

- [ ] **Step 1: Create the package directory**

Run: `mkdir -p /Users/jacob/Projects/odigos/odigos/core/heartbeat`

- [ ] **Step 2: Create utils.py with shared utility functions**

Read `odigos/core/heartbeat.py` and extract these two methods as standalone async functions. The functions receive the Heartbeat instance as `hb` parameter:
- `_send_notification` (around line 1426-1432)
- `_log_heartbeat_session` (around line 723-741)

Create `odigos/core/heartbeat/utils.py` with the exact code from those methods, but as module-level async functions that take `hb` as first parameter instead of `self`.

- [ ] **Step 3: Create __init__.py as empty placeholder**

Create `odigos/core/heartbeat/__init__.py` with just a comment:
```python
"""Heartbeat background loop — decomposed into focused modules."""
```

- [ ] **Step 4: Verify syntax**

Run: `python3 -c "import odigos.core.heartbeat; print('OK')"`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add odigos/core/heartbeat/
git commit -m "refactor(heartbeat): create package with utils module"
```

---

### Task 2: Extract scheduled tasks module

**Files:**
- Create: `odigos/core/heartbeat/scheduled.py`

- [ ] **Step 1: Extract scheduled task functions**

Read `odigos/core/heartbeat.py` and extract these methods as standalone async functions with `hb` parameter:
- `_maybe_send_briefing` (lines 261-299)
- `_process_scheduled_tasks` (lines 390-454)
- `_fire_reminders` (lines 456-477)
- `_reinsert_recurring_reminder` (lines 1434-1443)
- `_parse_recurrence_seconds` (lines 1446-1481, standalone function — no `hb` needed)

Write them to `odigos/core/heartbeat/scheduled.py`. Keep all original imports that these functions need. Functions should call `utils.send_notification(hb, ...)` instead of `self._send_notification(...)`.

- [ ] **Step 2: Verify syntax**

Run: `python3 -c "from odigos.core.heartbeat.scheduled import maybe_send_briefing, process_scheduled_tasks, fire_reminders; print('OK')"`

- [ ] **Step 3: Commit**

```bash
git add odigos/core/heartbeat/scheduled.py
git commit -m "refactor(heartbeat): extract scheduled tasks module"
```

---

### Task 3: Extract todos module

**Files:**
- Create: `odigos/core/heartbeat/todos.py`

- [ ] **Step 1: Extract todo functions**

Read `odigos/core/heartbeat.py` and extract:
- `_work_todos` (lines 479-493)
- `_execute_todo` (lines 495-536)

Write to `odigos/core/heartbeat/todos.py` as `work_todos(hb)` and `execute_todo(hb, todo)`. These call `utils.log_heartbeat_session(hb, ...)` and `utils.send_notification(hb, ...)`.

- [ ] **Step 2: Verify syntax**

Run: `python3 -c "from odigos.core.heartbeat.todos import work_todos; print('OK')"`

- [ ] **Step 3: Commit**

```bash
git add odigos/core/heartbeat/todos.py
git commit -m "refactor(heartbeat): extract todos module"
```

---

### Task 4: Extract plans module

**Files:**
- Create: `odigos/core/heartbeat/plans.py`

- [ ] **Step 1: Extract plan execution functions**

Read `odigos/core/heartbeat.py` and extract:
- `_work_in_progress_plans` (lines 614-721)
- The `_FAIL_MARKERS` constant and `_MAX_PLAN_RETRIES` that this method uses

Write to `odigos/core/heartbeat/plans.py` as `work_in_progress_plans(hb)`. Note: plan retry state (`_plan_fail_count`) stays on the Heartbeat instance — access via `hb._plan_fail_count`.

- [ ] **Step 2: Verify syntax**

Run: `python3 -c "from odigos.core.heartbeat.plans import work_in_progress_plans; print('OK')"`

- [ ] **Step 3: Commit**

```bash
git add odigos/core/heartbeat/plans.py
git commit -m "refactor(heartbeat): extract plans module"
```

---

### Task 5: Extract peers module

**Files:**
- Create: `odigos/core/heartbeat/peers.py`

- [ ] **Step 1: Extract peer-related functions**

Read `odigos/core/heartbeat.py` and extract:
- `_dispatch_as_subagent` (lines 376-388)
- `_process_peer_messages` (lines 538-609)
- `_deliver_subagent_results` (lines 824-844)
- `_peer_maintenance` (lines 912-940)
- The `_peer_filter = ContentFilter()` module-level instance

Write to `odigos/core/heartbeat/peers.py`. The `_peer_filter` becomes a module-level variable in this file.

- [ ] **Step 2: Verify syntax**

Run: `python3 -c "from odigos.core.heartbeat.peers import process_peer_messages, peer_maintenance; print('OK')"`

- [ ] **Step 3: Commit**

```bash
git add odigos/core/heartbeat/peers.py
git commit -m "refactor(heartbeat): extract peers module"
```

---

### Task 6: Extract idle and profiling modules

**Files:**
- Create: `odigos/core/heartbeat/idle.py`
- Create: `odigos/core/heartbeat/profiling.py`

- [ ] **Step 1: Extract idle thinking functions**

Read `odigos/core/heartbeat.py` and extract:
- `_idle_think` (lines 743-799)
- `_process_idle_response` (lines 801-822)
- The `_IDLE_THINK_FALLBACK` constant

Write to `odigos/core/heartbeat/idle.py`.

- [ ] **Step 2: Extract profiling functions**

Read `odigos/core/heartbeat.py` and extract:
- `_dream_analyze_user` (lines 1066-1230)
- `_extract_experiences` (lines 1232-1344)
- `_evaluate_plan_outcomes` (lines 1346-1424)

Write to `odigos/core/heartbeat/profiling.py`.

- [ ] **Step 3: Verify syntax**

Run: `python3 -c "from odigos.core.heartbeat.idle import idle_think; from odigos.core.heartbeat.profiling import dream_analyze_user; print('OK')"`

- [ ] **Step 4: Commit**

```bash
git add odigos/core/heartbeat/idle.py odigos/core/heartbeat/profiling.py
git commit -m "refactor(heartbeat): extract idle and profiling modules"
```

---

### Task 7: Extract maintenance module

**Files:**
- Create: `odigos/core/heartbeat/maintenance.py`

- [ ] **Step 1: Extract maintenance functions**

Read `odigos/core/heartbeat.py` and extract:
- `_run_evolution` (lines 888-910)
- `_check_for_updates` (lines 942-1009)
- `_check_storage_quota` (lines 1011-1064)
- `_check_email` (lines 301-326)
- `_send_nudges` (lines 328-350)
- `_check_followups` (lines 352-374)
- `_run_cron_jobs` (lines 846-886)

Write to `odigos/core/heartbeat/maintenance.py`.

- [ ] **Step 2: Verify syntax**

Run: `python3 -c "from odigos.core.heartbeat.maintenance import run_evolution, check_for_updates, run_cron_jobs; print('OK')"`

- [ ] **Step 3: Commit**

```bash
git add odigos/core/heartbeat/maintenance.py
git commit -m "refactor(heartbeat): extract maintenance module"
```

---

### Task 8: Create orchestrator and wire everything together

This is the critical task — replace the monolithic heartbeat.py with the orchestrator that imports from all modules.

**Files:**
- Create: `odigos/core/heartbeat/orchestrator.py`
- Modify: `odigos/core/heartbeat/__init__.py`
- Delete: `odigos/core/heartbeat.py` (the original monolith)

- [ ] **Step 1: Create orchestrator.py**

Read the original `odigos/core/heartbeat.py` and create `orchestrator.py` containing:
- All imports needed by `__init__`, `start`, `stop`, `_loop`, `_tick`
- The `Heartbeat` class with only: `__init__`, `start`, `stop`, `_loop`, `_tick`
- `_tick()` calls module functions instead of `self._method()`:
  - `await scheduled.maybe_send_briefing(self)` instead of `await self._maybe_send_briefing()`
  - `await todos.work_todos(self)` instead of `await self._work_todos()`
  - Same pattern for all phases
- All state initialization stays in `__init__` (tick counters, injected deps, config)
- Import the modules at the top:
  ```python
  from odigos.core.heartbeat import scheduled, todos, plans, peers, idle, profiling, maintenance
  ```

The `_tick()` method body stays exactly the same logic — only the call targets change from `self._method()` to `module.function(self)`.

- [ ] **Step 2: Update __init__.py to re-export Heartbeat**

```python
"""Heartbeat background loop — decomposed into focused modules."""
from odigos.core.heartbeat.orchestrator import Heartbeat

__all__ = ["Heartbeat"]
```

- [ ] **Step 3: Delete the original monolith**

Run: `rm /Users/jacob/Projects/odigos/odigos/core/heartbeat.py`

Note: This file was already replaced by the package directory. If git sees it as a conflict (file vs directory), the `git rm` + `git add` in the commit step handles it.

- [ ] **Step 4: Verify import still works**

Run: `python3 -c "from odigos.core.heartbeat import Heartbeat; print(Heartbeat.__name__)"`
Expected: `Heartbeat`

- [ ] **Step 5: Run existing tests**

Run: `python3 -m pytest tests/ -x -q`
Expected: All tests pass (no tests directly test heartbeat internals)

- [ ] **Step 6: Commit**

```bash
git rm odigos/core/heartbeat.py 2>/dev/null; git add odigos/core/heartbeat/
git commit -m "refactor(heartbeat): replace monolith with package orchestrator"
```

---

### Task 9: Extract ChatPanel — WelcomeView, ArtifactGallery, VoiceModePanel

Start with the simplest extractions — three small inline components that have no shared state complexity.

**Files:**
- Create: `dashboard/src/components/chat/WelcomeView.tsx`
- Create: `dashboard/src/components/chat/ArtifactGallery.tsx`
- Create: `dashboard/src/components/chat/VoiceModePanel.tsx`
- Modify: `dashboard/src/components/ChatPanel.tsx`

- [ ] **Step 1: Create chat/ directory**

Run: `mkdir -p /Users/jacob/Projects/odigos/dashboard/src/components/chat`

- [ ] **Step 2: Extract WelcomeView**

Read `ChatPanel.tsx` and find the `WelcomeView` component (around lines 79-114). Move it to `chat/WelcomeView.tsx` as a named export. Add necessary imports (React, icons, etc.). Define its props interface based on what it receives.

- [ ] **Step 3: Extract ArtifactGallery**

Read `ChatPanel.tsx` and find `ImageArtifact` (lines 35-50) and `AudioArtifact` (lines 52-77). Move both to `chat/ArtifactGallery.tsx`. Export `ArtifactGallery` as the main component that renders a list of artifacts. `ImageArtifact` and `AudioArtifact` are local to this file.

- [ ] **Step 4: Extract VoiceModePanel**

Read `ChatPanel.tsx` and find the voice mode view section (lines 416-433). Move to `chat/VoiceModePanel.tsx`. Define props interface.

- [ ] **Step 5: Update ChatPanel.tsx imports**

Replace the inline component definitions with imports:
```typescript
import { WelcomeView } from './chat/WelcomeView'
import { ArtifactGallery } from './chat/ArtifactGallery'
import { VoiceModePanel } from './chat/VoiceModePanel'
```

Remove the inline component code from ChatPanel.tsx.

- [ ] **Step 6: Verify build**

Run: `cd /Users/jacob/Projects/odigos/dashboard && npx tsc --noEmit`
Expected: No type errors

- [ ] **Step 7: Commit**

```bash
git add dashboard/src/components/chat/ dashboard/src/components/ChatPanel.tsx
git commit -m "refactor(ChatPanel): extract WelcomeView, ArtifactGallery, VoiceModePanel"
```

---

### Task 10: Extract ChatPanel — SuggestedActions, MessageDisplay, ChatInputArea

The larger extractions that significantly slim down ChatPanel.

**Files:**
- Create: `dashboard/src/components/chat/SuggestedActions.tsx`
- Create: `dashboard/src/components/chat/MessageDisplay.tsx`
- Create: `dashboard/src/components/chat/ChatInputArea.tsx`
- Modify: `dashboard/src/components/ChatPanel.tsx`

- [ ] **Step 1: Extract SuggestedActions**

Read `ChatPanel.tsx` and find the suggested actions section (around lines 580-622). Move to `chat/SuggestedActions.tsx`. Props: `actions: string[]`, `showAll: boolean`, `onToggleShowAll: () => void`, `onSelect: (action: string) => void`.

- [ ] **Step 2: Extract MessageDisplay**

Read `ChatPanel.tsx` and find the message display section (around lines 406-578). This is the largest extraction. Move to `chat/MessageDisplay.tsx`. It renders:
- Welcome view (via `<WelcomeView>` import)
- Voice mode (via `<VoiceModePanel>` import)
- Conversation switching skeleton
- Message list with history loading button
- Streaming content display
- Thinking state indicator
- Artifact gallery (via `<ArtifactGallery>` import)

Define props interface based on all the state it consumes from ChatPanel.

- [ ] **Step 3: Extract ChatInputArea**

Read `ChatPanel.tsx` and find the input area section (around lines 624-777). Move to `chat/ChatInputArea.tsx`. It renders:
- Pending files list with remove buttons
- Navigation breadcrumbs
- Textarea with auto-height
- Action buttons (attach, camera, voice, send)

Define props interface.

- [ ] **Step 4: Update ChatPanel.tsx**

ChatPanel.tsx should now be ~200 lines: state declarations, effects, handlers, and a render that composes the extracted components:

```tsx
return (
  <div className="...">
    <MessageDisplay ... />
    <SuggestedActions ... />
    <ChatInputArea ... />
  </div>
)
```

- [ ] **Step 5: Verify build**

Run: `cd /Users/jacob/Projects/odigos/dashboard && npx tsc --noEmit`
Expected: No type errors

- [ ] **Step 6: Commit**

```bash
git add dashboard/src/components/chat/ dashboard/src/components/ChatPanel.tsx
git commit -m "refactor(ChatPanel): extract MessageDisplay, ChatInputArea, SuggestedActions"
```

---

### Task 11: Extract AppLayout — useRouteState and useKeyboardShortcuts hooks

Start with the two simplest hooks.

**Files:**
- Create: `dashboard/src/layouts/hooks/useRouteState.ts`
- Create: `dashboard/src/layouts/hooks/useKeyboardShortcuts.ts`
- Modify: `dashboard/src/layouts/AppLayout.tsx`

- [ ] **Step 1: Create hooks/ directory**

Run: `mkdir -p /Users/jacob/Projects/odigos/dashboard/src/layouts/hooks`

- [ ] **Step 2: Create useRouteState hook**

Read `AppLayout.tsx` and find the route detection logic (boolean checks like `pathname.startsWith('/settings')`). Create `hooks/useRouteState.ts`:

```typescript
import { useLocation } from 'react-router-dom'

export function useRouteState() {
  const { pathname } = useLocation()
  return {
    isSettings: pathname.startsWith('/settings'),
    isNotebook: pathname.startsWith('/notebooks'),
    isKanban: pathname.startsWith('/kanban'),
    isImages: pathname.startsWith('/images'),
  }
}
```

- [ ] **Step 3: Create useKeyboardShortcuts hook**

Read `AppLayout.tsx` and find the keydown effect (Cmd+K, Cmd+N, Escape). Extract to `hooks/useKeyboardShortcuts.ts`. It receives callbacks as params.

- [ ] **Step 4: Update AppLayout.tsx**

Replace inline route checks and keyboard effect with hook calls:
```typescript
import { useRouteState } from './hooks/useRouteState'
import { useKeyboardShortcuts } from './hooks/useKeyboardShortcuts'

const { isSettings, isNotebook, isKanban, isImages } = useRouteState()
useKeyboardShortcuts({ onNewChat: handleNewChat, onSwitcher: () => setSwitcherOpen(true) })
```

Remove the inline code that was extracted.

- [ ] **Step 5: Verify build**

Run: `cd /Users/jacob/Projects/odigos/dashboard && npx tsc --noEmit`

- [ ] **Step 6: Commit**

```bash
git add dashboard/src/layouts/hooks/ dashboard/src/layouts/AppLayout.tsx
git commit -m "refactor(AppLayout): extract useRouteState and useKeyboardShortcuts hooks"
```

---

### Task 12: Extract AppLayout — useConversationActions hook

**Files:**
- Create: `dashboard/src/layouts/hooks/useConversationActions.ts`
- Modify: `dashboard/src/layouts/AppLayout.tsx`

- [ ] **Step 1: Create useConversationActions hook**

Read `AppLayout.tsx` and extract these handlers and their associated state:
- `editingId`, `editTitle`, `setEditTitle`, `editInputRef` state
- `handleNewChat` (lines 524-534)
- `handleSelectConversation` (lines 536-541)
- `handleSelectImage` (lines 543-546)
- `startRename` (lines 548-556)
- `confirmRename` (lines 558-565)
- `handleDelete` (lines 567-574)
- `handleExport` (lines 576-587)
- `displayTitle` (lines 589-595)

Write to `hooks/useConversationActions.ts`. The hook owns the rename state and returns all handlers plus `editingId`, `editTitle`, `setEditTitle`, `editInputRef`.

- [ ] **Step 2: Update AppLayout.tsx**

Replace the 8 handler definitions and 4 state declarations with:
```typescript
import { useConversationActions } from './hooks/useConversationActions'

const {
  handleNewChat, handleSelectConversation, handleSelectImage,
  startRename, confirmRename, handleDelete, handleExport, displayTitle,
  editingId, editTitle, setEditTitle, editInputRef,
} = useConversationActions()
```

- [ ] **Step 3: Verify build**

Run: `cd /Users/jacob/Projects/odigos/dashboard && npx tsc --noEmit`

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/layouts/hooks/useConversationActions.ts dashboard/src/layouts/AppLayout.tsx
git commit -m "refactor(AppLayout): extract useConversationActions hook"
```

---

### Task 13: Extract AppLayout — useWebSocketHandler hook and AppSidebar

**Files:**
- Create: `dashboard/src/layouts/hooks/useWebSocketHandler.ts`
- Create: `dashboard/src/layouts/AppSidebar.tsx`
- Modify: `dashboard/src/layouts/AppLayout.tsx`

- [ ] **Step 1: Extract useWebSocketHandler hook**

Read `AppLayout.tsx` and find the WebSocket connection setup and message routing (around lines 418-513). Extract to `hooks/useWebSocketHandler.ts`. The hook:
- Creates and manages the WebSocket connection
- Routes all message types (notification, chat_chunk, chat_response, stream_end, queue_update, title_updated, etc.)
- Returns `{ socketRef, connected }`
- Reads/writes Zustand stores directly (same as current inline code)

- [ ] **Step 2: Extract AppSidebar**

Read `AppLayout.tsx` and find the memoized `AppSidebar` component (around lines 105-305). Move to `AppSidebar.tsx` as a named export. Keep the `React.memo` wrapper. Keep the same props interface.

- [ ] **Step 3: Update AppLayout.tsx**

AppLayout.tsx should now be ~200 lines:
- Import hooks: `useRouteState`, `useKeyboardShortcuts`, `useConversationActions`, `useWebSocketHandler`
- Import `AppSidebar` from `./AppSidebar`
- Call hooks, destructure returns
- Render layout shell: QuickSwitcher, mobile menu, AppSidebar, Outlet, ChatPanel, ArtifactPreview

```typescript
import { AppSidebar } from './AppSidebar'
import { useWebSocketHandler } from './hooks/useWebSocketHandler'
import { useConversationActions } from './hooks/useConversationActions'
import { useRouteState } from './hooks/useRouteState'
import { useKeyboardShortcuts } from './hooks/useKeyboardShortcuts'
```

- [ ] **Step 4: Verify build**

Run: `cd /Users/jacob/Projects/odigos/dashboard && npx tsc --noEmit`

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/layouts/
git commit -m "refactor(AppLayout): extract WebSocket handler and sidebar"
```

---

### Task 14: Final integration verification

- [ ] **Step 1: Run backend tests**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/ -x -q`
Expected: All tests pass

- [ ] **Step 2: Verify heartbeat import chain**

Run:
```bash
python3 -c "
from odigos.core.heartbeat import Heartbeat
from odigos.core.heartbeat import scheduled, todos, plans, peers, idle, profiling, maintenance, utils
print('All heartbeat modules importable')
print(f'Heartbeat.__module__: {Heartbeat.__module__}')
"
```
Expected: All imports succeed, module is `odigos.core.heartbeat.orchestrator`

- [ ] **Step 3: Verify frontend build**

Run: `cd /Users/jacob/Projects/odigos/dashboard && npx tsc --noEmit`
Expected: No type errors

- [ ] **Step 4: Verify frontend dev server starts**

Run: `cd /Users/jacob/Projects/odigos/dashboard && npx vite build 2>&1 | tail -5`
Expected: Build succeeds

- [ ] **Step 5: Check file sizes achieved targets**

Run:
```bash
echo "=== Backend ==="
wc -l odigos/core/heartbeat/orchestrator.py
wc -l odigos/core/heartbeat/*.py | tail -1
echo "=== Frontend ==="
wc -l dashboard/src/components/ChatPanel.tsx
wc -l dashboard/src/layouts/AppLayout.tsx
```
Expected: orchestrator.py ~260 lines, ChatPanel.tsx ~200 lines, AppLayout.tsx ~200 lines

- [ ] **Step 6: Commit any final fixes**

```bash
git add -A
git commit -m "fix: final cleanup for decomposition"
```
