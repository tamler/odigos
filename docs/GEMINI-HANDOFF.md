# Gemini Frontend Handoff

This document is a coordination file between Claude (backend/integration) and Gemini (frontend). Both agents can read and update this file to communicate status, decisions, and blockers.

**Last updated**: 2026-03-19 by Claude

---

## Project Overview

Odigos is a self-hosted AI agent platform. The dashboard is a React 19 SPA at `dashboard/` that communicates with a Python/FastAPI backend via REST API and WebSocket.

**Tech Stack:**
- React 19, TypeScript, Vite
- Tailwind CSS v4 + shadcn/ui components
- react-router-dom v7
- Recharts (charts)
- shadcn-kanban-board (drag-drop)
- Sonner (toasts)
- lucide-react (icons)

**Key Files:**
- `dashboard/src/App.tsx` -- Routes
- `dashboard/src/layouts/AppLayout.tsx` -- Main layout with sidebar, WebSocket, navigation
- `dashboard/src/pages/ChatPage.tsx` -- Primary chat interface
- `dashboard/src/lib/api.ts` -- HTTP helpers (get, post, patch, del)
- `dashboard/src/lib/ws.ts` -- WebSocket client (ChatSocket class)
- `dashboard/src/lib/auth.ts` -- Auth helpers

---

## Tasks for Gemini

### Task G1: Fix Status Indicators

**Priority:** High
**Status:** Not started

**Problem:** The thinking/status indicator in ChatPage sometimes doesn't render when the agent is processing. Users see no feedback that their message is being handled.

**Root Cause:** The `thinking` state is set to `true` on send (line 234 of ChatPage.tsx), but status text depends on `status` WebSocket messages from the server. If the server is slow to send status events, there's a gap where `thinking` is true but no text shows -- just dots.

**Current code** (ChatPage.tsx lines 321-326):
```tsx
{thinking && (
  <div className="flex items-center gap-2">
    <Loader variant="typing" />
    {status && <span className="text-xs text-muted-foreground animate-pulse">{status}</span>}
  </div>
)}
```

**Fix:**
1. Always show a default status message when `thinking` is true, even without a server status event. Something like "Thinking..." as the default.
2. The queue system now sends `queue_update` with `queued: 0` when processing completes. The frontend already handles this (sets `thinking = false`). But there may be edge cases where `thinking` stays true if the WebSocket disconnects mid-processing. Add a timeout fallback.

**Files to modify:**
- `dashboard/src/pages/ChatPage.tsx`

**Testing:** Send a message, verify the indicator appears immediately and stays visible until the response arrives.

---

### Task G2: Fix Conversation Switching

**Priority:** High
**Status:** Not started

**Problem:** When switching conversations while the agent is processing, the thinking indicator persists in the new conversation. Also, the response from the old conversation may arrive and get displayed in the wrong conversation.

**Current flow:**
1. User sends message in conversation A
2. `thinking = true`, waiting for response
3. User clicks conversation B in sidebar
4. URL changes to `/?c=B`, ChatPage loads B's messages
5. BUT `thinking` is still true from A
6. When A's response arrives via WebSocket, it gets appended to messages (now showing B)

**Fix:**
1. When conversation switches (detected in the `useEffect` at line 82-109), reset `thinking = false` and `status = null`
2. Track which `conversation_id` a pending response belongs to. When `chat_response` arrives, check if `msg.conversation_id` matches the currently active conversation. If not, don't append it to the visible messages (but the backend has already saved it to the DB, so it's not lost).

**Files to modify:**
- `dashboard/src/pages/ChatPage.tsx`

**Key state:** `activeConversationId` from outlet context, `loadedConvRef` for tracking which conv is displayed.

---

### Task G3: Fix Auto-Titles Not Triggering

**Priority:** Medium
**Status:** Not started

**Problem:** Auto-titles for new conversations aren't reliably showing in the sidebar after the first exchange.

**How it should work:**
1. User sends first message, agent responds
2. Backend runs `_auto_title_and_notify()` as a background task
3. Backend sends `title_updated` WebSocket message
4. Frontend calls `refreshConversations()` to reload sidebar

**Possible issues:**
1. The `title_updated` handler (ChatPage.tsx line 72) calls `refreshConversations()` which reloads the full list via GET `/api/conversations?limit=50`. If the title hasn't been written to DB yet when the refresh fires, it won't show.
2. The `conversation_started` event (line 66) sets the active ID and refreshes, but this races with `title_updated`.
3. The auto-title LLM call might be failing silently. Check the backend logs for "Auto-title/notify failed" warnings.

**Fix:**
1. When `title_updated` arrives, update the specific conversation in local state directly (don't rely solely on a full refresh). The message includes `conversation_id` and `title`:
```tsx
if (msg.type === 'title_updated' && msg.conversation_id && msg.title) {
  // Update in AppLayout's conversation list directly
  // AND refresh in case of other updates
  refreshConversations()
}
```
2. The `title_updated` handler is in ChatPage but the conversation list is in AppLayout. The handler should be in AppLayout's `baseHandler` instead, so it fires regardless of which page is active.

**Files to modify:**
- `dashboard/src/layouts/AppLayout.tsx` (move title_updated handling to baseHandler)
- `dashboard/src/pages/ChatPage.tsx` (remove redundant title_updated handler)

---

### Task G4: Mobile Polish Pass

**Priority:** Medium
**Status:** Not started

**Problem:** Mobile experience needs testing and refinement. The responsive layout exists but hasn't been thoroughly device-tested.

**Known issues to check:**
1. Sidebar animation on open/close (should be smooth 200ms slide)
2. Backdrop dismissal (tap outside sidebar should close it)
3. Chat input area on mobile -- keyboard handling, viewport resize
4. Navigation buttons (Analytics, Kanban, Notebooks, Settings) -- touch targets need to be at least 44px
5. NotebookPage, KanbanPage, AnalyticsPage -- need responsive testing
6. KanbanPage columns should scroll horizontally on mobile
7. AnalyticsPage charts need to be touch-friendly and not overflow

**Current breakpoint:** `lg` (1024px) is the primary mobile/desktop breakpoint.

**Files to check:**
- `dashboard/src/layouts/AppLayout.tsx` (sidebar, top bar)
- `dashboard/src/pages/ChatPage.tsx` (input area, messages)
- `dashboard/src/pages/NotebookPage.tsx` (contextual chat hidden on mobile already)
- `dashboard/src/pages/KanbanPage.tsx` (columns layout)
- `dashboard/src/pages/AnalyticsPage.tsx` (charts)

---

### Task G5: Cowork Layout (Phase 3 Flagship)

**Priority:** High (but start after G1-G4)
**Status:** Not started

**Goal:** Rearchitect the layout so any page can have a contextual agent chat panel alongside it. Currently the chat is its own page. The vision is:

```
[Sidebar] | [Main Content (notebook/kanban/docs)] | [Agent Chat Panel]
```

**Design requirements:**
1. Three-panel layout: sidebar (existing) + main content + optional chat panel
2. Chat panel slides in/out, can be toggled
3. When chat panel is open on a content page (notebooks, kanban), messages include `context` metadata so the agent knows what the user is looking at
4. The context_metadata mechanism already exists in the backend (ws.py passes `data.context` through to the agent chain)
5. On mobile: chat panel is full-screen overlay, not side-by-side
6. The existing ChatPage becomes the "chat-only" view (main content IS the chat)

**Context metadata already works:**
The WebSocket `chat` message can include a `context` field:
```json
{"type": "chat", "content": "...", "context": {"notebook_id": "abc"}}
```
or
```json
{"type": "chat", "content": "...", "context": {"board_id": "xyz"}}
```

The backend threads this through to the agent, which gets notebook/board content injected into its system prompt.

**Implementation approach:**
1. Create a `ChatPanel` component extracted from ChatPage's chat UI
2. AppLayout gets a `chatPanelOpen` state and renders `<ChatPanel>` as a right panel
3. Content pages (NotebookPage, KanbanPage) can trigger chat panel open and pass context
4. ChatPage itself uses the same ChatPanel but full-width (no side panel)

**Files to create/modify:**
- Create: `dashboard/src/components/ChatPanel.tsx` (extracted from ChatPage)
- Modify: `dashboard/src/layouts/AppLayout.tsx` (three-panel layout)
- Modify: `dashboard/src/pages/ChatPage.tsx` (use ChatPanel)
- Modify: `dashboard/src/pages/NotebookPage.tsx` (chat panel integration)
- Modify: `dashboard/src/pages/KanbanPage.tsx` (chat panel integration)

---

## Architecture Reference

### WebSocket Message Types

**Server -> Client:**
| Type | Fields | Purpose |
|---|---|---|
| `connected` | session_id, conversation_id | Connection established |
| `status` | text | Processing status update |
| `chat_response` | content, conversation_id | Agent response |
| `conversation_started` | conversation_id | New conversation created |
| `title_updated` | conversation_id, title | Auto-title generated |
| `queue_update` | queued | Messages remaining in queue |
| `message_queued` | queued, message | Message accepted into queue |
| `queue_full` | queued, message | Queue at capacity (max 3) |
| `notification` | title, body/message, priority | Toast notification |
| `peer_connected` | conversation_id, agent_name | Peer agent connected |
| `approval_resolved` | approval_id, decision, resolved | Tool approval result |
| `subscribed` | channels | Subscription confirmed |

**Client -> Server:**
| Type | Fields | Purpose |
|---|---|---|
| `chat` | content, conversation_id?, context?, attachments? | Send message |
| `auth` | token | Authenticate (first message fallback) |
| `peer_connect` | agent_name | Identify as peer |
| `approval_response` | approval_id, decision | Approve/deny tool |
| `subscribe` | channels | Subscribe to events |

### API Endpoints Used by Frontend

**Chat/Conversations:**
- `GET /api/conversations?limit=50` -- List conversations
- `GET /api/conversations/{id}/messages` -- Load messages
- `PATCH /api/conversations/{id}` -- Update title
- `DELETE /api/conversations/{id}` -- Delete conversation
- `GET /api/conversations/{id}/export?format=json|markdown` -- Export

**Notebooks:**
- `GET /api/notebooks` -- List notebooks
- `POST /api/notebooks` -- Create notebook (returns flat notebook object)
- `GET /api/notebooks/{id}` -- Get notebook with entries (flat: `{...notebook, entries: [...]}`)
- `PATCH /api/notebooks/{id}` -- Update notebook
- `DELETE /api/notebooks/{id}` -- Delete notebook
- `POST /api/notebooks/{id}/entries` -- Add entry (returns flat entry object)
- `PATCH /api/notebooks/{id}/entries/{eid}` -- Update entry
- `DELETE /api/notebooks/{id}/entries/{eid}` -- Delete entry
- `POST /api/notebooks/{id}/entries/{eid}/accept` -- Accept suggestion
- `POST /api/notebooks/{id}/entries/{eid}/reject` -- Reject suggestion

**Kanban:**
- `GET /api/kanban/boards` -- List boards
- `POST /api/kanban/boards` -- Create board (auto-creates 4 default columns)
- `GET /api/kanban/boards/{id}` -- Get board (flat: `{...board, columns: [...], cards: [...]}`)
- `PATCH /api/kanban/boards/{id}` -- Update board
- `DELETE /api/kanban/boards/{id}` -- Delete board
- `POST /api/kanban/boards/{id}/columns` -- Add column
- `PATCH /api/kanban/boards/{id}/columns/{cid}` -- Update column
- `DELETE /api/kanban/boards/{id}/columns/{cid}` -- Delete column
- `POST /api/kanban/boards/{id}/cards` -- Create card (column_id in body)
- `PATCH /api/kanban/boards/{id}/cards/{kid}` -- Update card
- `DELETE /api/kanban/boards/{id}/cards/{kid}` -- Delete card
- `POST /api/kanban/boards/{id}/cards/{kid}/move` -- Move card (`{column_id, position}`)
- `PATCH /api/kanban/boards/{id}/reorder` -- Batch reorder

**Analytics:**
- `GET /api/analytics/overview` -- Summary metrics
- `GET /api/analytics/classifications` -- Query classification stats
- `GET /api/analytics/skills` -- Skill usage stats
- `GET /api/analytics/errors` -- Tool error stats
- `GET /api/analytics/plans` -- Active plans with completion

**Auth:**
- `GET /api/auth/status` -- Auth state
- `POST /api/auth/login` -- Login
- `POST /api/auth/setup` -- First-time setup
- `POST /api/auth/logout` -- Logout
- `POST /api/auth/change-password` -- Change password

**Other:**
- `GET /api/settings` -- Current settings
- `POST /api/upload` -- File upload (FormData)
- `GET /api/state` -- Agent state inspection

### Outlet Context (from AppLayout to child pages)

```tsx
interface OutletCtx {
  activeConversationId: string | null
  setActiveId: (id: string | null) => void
  refreshConversations: () => void
  socketRef: React.MutableRefObject<ChatSocket | null>
  connected: boolean
}
```

### Available UI Components (shadcn)

All in `dashboard/src/components/ui/`:
Button, Input, Textarea, Card, Badge, Avatar, Alert, Dialog, DropdownMenu, Tabs, Select, Switch, Label, Separator, ScrollArea, Tooltip, HoverCard, Skeleton, Collapsible

Custom components: Loader (11 variants), Markdown, CodeBlock, ChatContainer, FileUpload, Source, Kanban

### CSS/Theme

- Tailwind v4 with CSS custom properties
- Dark/light mode via `next-themes`
- Chart colors: `hsl(var(--primary))`, `hsl(var(--muted-foreground))`
- Primary breakpoint: `lg` (1024px)

---

## Conventions

1. **API responses are flat objects**, not wrapped (e.g. `create_notebook` returns `{id, title, ...}` not `{notebook: {...}}`)
2. **Use `get/post/patch/del` from `@/lib/api`** for all HTTP calls
3. **Use `toast` from `sonner`** for notifications
4. **Use `lucide-react`** for all icons
5. **Responsive: `lg:` prefix** for desktop-specific styles
6. **No mocks in tests** -- use real data
7. **TypeScript must compile**: `cd dashboard && npx tsc --noEmit`
8. **Build must succeed**: `cd dashboard && npm run build`

---

## Communication Log

### 2026-03-19 (Claude)
- Completed Phase 2: Notebooks, Kanban, Analytics
- Fixed WebSocket message stomping with asyncio.Queue (ws.py)
- Frontend queue handling added to ChatPage
- Created this handoff document
- Tasks G1-G5 defined above for Gemini

### Notes for Claude review
_Gemini: leave notes here about completed work, questions, or blockers. Claude will review._

---
