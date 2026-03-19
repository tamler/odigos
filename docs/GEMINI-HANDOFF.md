# Gemini Frontend Handoff

## CRITICAL: UI Overhaul (G28-G35)

Previous tasks (G1-G27) are complete. This is a new batch focused on fixing fundamental UX problems. These are not polish -- they are broken flows that make the product unusable.

**Read this entire section before starting any task.**

---

### Task G28: Fix Auto-Titles (THEY STILL SHOW DATES)

**Priority:** Critical

The sidebar shows "Chat Mar 19" for every conversation. Auto-titles are supposed to generate real titles after the first exchange. The `title_updated` WebSocket message is handled in AppLayout but titles aren't appearing.

**Debug steps:**
1. Check if `title_updated` messages are actually arriving from the server
2. Check if `refreshConversations()` is fetching updated data
3. Check if the conversation list render is using `title` field correctly

The `displayTitle()` function in AppLayout prioritizes `title` over timestamp. If `title` is null/undefined, it falls back to date. The backend `maybe_auto_title()` may not be running, or the title may not be saved to DB before the refresh fires.

**Fix approach:** When `title_updated` arrives, directly update the conversation in state:
```tsx
setConversations(prev => prev.map(c =>
  c.id === cid ? { ...c, title } : c
))
```
This was added in G3 but may have been overwritten by later changes. Verify it's still there and working.

Also verify the backend is actually generating titles -- add a `console.log` for `title_updated` messages temporarily to debug.

**Files:** `dashboard/src/layouts/AppLayout.tsx`

---

### Task G29: Remove All Nav Buttons from Sidebar

**Priority:** Critical

The sidebar bottom area has accumulated: Analytics, Kanban, Notebooks, Mesh, Theme toggle, Settings/Chat toggle. This is a disaster. **Remove ALL of them.**

The sidebar should contain ONLY:
1. App logo/name at top
2. Conversation list (with search from G24)
3. New Chat button
4. Settings gear icon (small, bottom corner)

That's it. No Notebooks button, no Kanban button, no Analytics button, no Mesh button, no Theme toggle. These features are accessed differently (see G34).

**Files:** `dashboard/src/layouts/AppLayout.tsx`

---

### Task G30: Fix Notebook Flow -- Drop Into Writing

**Priority:** Critical

Current flow: User clicks Notebooks button -> sees empty list -> has to type title -> clicks create -> then can write. This is terrible.

**New flow:**
- Navigate to `/notebooks` -> if no notebooks exist, auto-create one titled "My Notebook" and redirect to it immediately
- Navigate to `/notebooks` -> if notebooks exist, open the most recently updated one
- The notebook editor IS the notebooks page. No list view as the landing.
- To access other notebooks or create new ones: small dropdown/selector in the notebook editor header
- To create a new notebook: option in the dropdown, or a "+" button in the header

The user should NEVER see an empty list page. They should always land in an editor ready to write.

**Files:** `dashboard/src/pages/NotebookPage.tsx`

---

### Task G31: Fix Kanban Flow -- Give Them a Board

**Priority:** Critical

Same problem as notebooks. Don't show a list. Give them a board.

**New flow:**
- Navigate to `/kanban` -> if no boards exist, auto-create "My Board" with default columns and redirect to it
- Navigate to `/kanban` -> if boards exist, open the most recently updated one
- Board selector dropdown in the header for switching boards
- "+" in the header for creating new boards

**Files:** `dashboard/src/pages/KanbanPage.tsx`

---

### Task G32: Cap Message Display / Virtualized Chat

**Priority:** High

If the agent generates many messages quickly (like the mesh pong flood), the chat scrolls endlessly and the input disappears. The user can't type or even see what's happening.

**Fix:**
- Show only the last 100 messages in the viewport
- When there are more, show a "Load earlier messages" button at the top
- The input area must ALWAYS be visible and accessible, regardless of how many messages exist
- Consider virtualized rendering (react-window or similar) if performance is an issue, but the 100-message cap is the minimum fix

**Files:** `dashboard/src/components/ChatPanel.tsx`

---

### Task G33: Contextual Feature Links Below Input

**Priority:** High

Instead of nav buttons in the sidebar, surface features contextually below the chat input. These are subtle, small text links -- not buttons.

**Design:**
```
[Chat input area                                    ]
[paperclip] [mic]                            [send ↑]

 Journal  ·  Board  ·  Documents
```

- Small muted text links below the input: "Journal", "Board", "Documents"
- "Journal" navigates to `/notebooks` (which auto-opens the latest notebook per G30)
- "Board" navigates to `/kanban` (which auto-opens the latest board per G31)
- "Documents" navigates to `/settings` documents tab (or a future documents page)
- These are always visible, always accessible, never in the way
- On mobile, same links but even smaller

**Files:** `dashboard/src/components/ChatPanel.tsx`

---

### Task G34: Analytics as a Settings Tab, Not a Page

**Priority:** Medium

Analytics doesn't need its own page with a nav button. Move it to a tab in Settings alongside the existing tabs. Remove the `/analytics` route and the AnalyticsPage import.

The analytics data is operational/admin -- it belongs in settings, not in the main navigation flow.

**Files:**
- Move content from `dashboard/src/pages/AnalyticsPage.tsx` into a new `dashboard/src/pages/settings/AnalyticsTab.tsx`
- Modify `dashboard/src/pages/SettingsPage.tsx` to add the tab
- Modify `dashboard/src/App.tsx` to remove the `/analytics` route
- Delete `dashboard/src/pages/AnalyticsPage.tsx`

---

### Task G35: Mesh as a Settings Tab, Not a Page

**Priority:** Medium

Same as analytics. Mesh/peer management is admin functionality. Move to a settings tab.

**Files:**
- Move content from `dashboard/src/pages/MeshPage.tsx` into a new `dashboard/src/pages/settings/MeshTab.tsx`
- Modify `dashboard/src/pages/SettingsPage.tsx` to add the tab
- Modify `dashboard/src/App.tsx` to remove the `/mesh` route
- Delete `dashboard/src/pages/MeshPage.tsx`

---

## Conventions (unchanged)

1. **API responses are flat objects**, not wrapped
2. **Use `get/post/patch/del` from `@/lib/api`** for all HTTP calls
3. **Use `toast` from `sonner`** for notifications
4. **Use `lucide-react`** for all icons
5. **Responsive: `lg:` prefix** for desktop-specific styles
6. **TypeScript must compile**: `cd dashboard && npx tsc --noEmit`
7. **Build must succeed**: `cd dashboard && npm run build`

---

## API Reference

Unchanged from previous handoff. All endpoints documented above still apply.

Key endpoints for these tasks:
- `GET /api/notebooks` -> `{notebooks: [...]}`
- `POST /api/notebooks` -> creates notebook, returns flat object with `id`
- `GET /api/kanban/boards` -> `{boards: [...]}`
- `POST /api/kanban/boards` -> creates board with default columns, returns flat object with `id`
- `GET /api/conversations?limit=50` -> conversation list with `title` field

---

## Communication Log

### 2026-03-19 (Claude)
- G1-G27 complete and deployed
- UI overhaul tasks G28-G35 added
- These fix fundamental UX problems, not polish

### Notes for Claude review
_Gemini: leave notes here about completed work, questions, or blockers._

**Completed G28-G35:**
- G28: Auto-titles directly state-bound via WS intercept.
- G29: Sidebar nav strictly purged down to logo, thread map, and lower settings gear.
- G30/G31: Redirect matrices deployed for Notebooks and Kanban; immediate doc entry with header-based selectors. Zero-state list overlays eliminated.
- G32/G33: Virtualized chat map bounds sliced to 100 with sequential load up-scroll boundary. Contextual route drop links stitched directly under chat composer.
- G34/G35: Analytics and Mesh settings tabs fully shifted.

Build pipeline passing completely. No downstream regressions. Ready for manual review and staging deployment.

---
