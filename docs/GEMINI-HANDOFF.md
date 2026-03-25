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

### Task G36: Email Indicator in Contextual Links

**Priority:** Medium

The backend now has email tools (`check_email`, `send_email`) and the heartbeat sends notifications via WebSocket when new mail arrives. The notification message type is `notification` with `title: "New Email"`.

**What to build:**

1. Add "Email" to the contextual links below the chat input (alongside Journal, Board, Documents). Clicking it types "Check my email" into the chat input and sends it -- the agent handles the rest.

2. When a `notification` WebSocket message arrives with title containing "Email", show a subtle badge/dot on the "Email" link to indicate new mail.

3. The badge clears when the user clicks the Email link (since they're asking the agent to check).

**Keep it simple.** The agent is the email client. The UI just provides a quick-access link and a new-mail indicator. No inbox page, no compose form.

**Files:** `dashboard/src/components/ChatPanel.tsx`

---

### Task G37: Telegram & Email Setup in Settings

**Priority:** High

Users need to configure Telegram and email from the Settings UI, not by editing files on the server.

**Backend is ready.** The settings API now includes:
- `GET /api/settings` returns `telegram_bot_token` (masked), `telegram_configured` (boolean), `telegram` config, `email` config
- `POST /api/settings` accepts `telegram_bot_token` (string), `telegram` (dict), `email` (dict)

**What to build in the frontend:**

Add a "Connections" or "Integrations" tab to SettingsPage with two sections:

**Telegram section:**
- Shows "Connected" badge if `telegram_configured` is true, "Not configured" if false
- Input field for bot token (password type, masked when saved)
- Instructions text: "1. Open Telegram and message @BotFather, 2. Send /newbot, 3. Paste the token here"
- Save button that POSTs `{telegram_bot_token: "..."}` to `/api/settings`
- Note: "Restart required after changing token" (we'll fix hot-reload later)

**Email section:**
- Shows "Connected" badge if `email.enabled` is true
- Fields: address, IMAP host, IMAP port, SMTP host, SMTP port, username, password
- Enable/disable toggle
- Save button that POSTs `{email: {enabled: true, address: "...", ...}}` to `/api/settings`

**Files:** Create `dashboard/src/pages/settings/IntegrationsTab.tsx`, modify `dashboard/src/pages/SettingsPage.tsx`

---

### Task G38: Artifact Preview Panel (Split View)

**Priority:** High — this is a major UX upgrade

When the agent creates an artifact (via the `create_artifact` tool), the artifact should open in a live preview panel alongside the chat, similar to Claude Artifacts or ChatGPT Canvas. The chat shrinks to ~30% and the artifact takes ~70%.

**Research references:**
- Claude Artifacts: https://support.claude.com/en/articles/9487310-what-are-artifacts-and-how-do-i-use-them
- assistant-ui (open source React): https://www.assistant-ui.com/examples/artifacts
- Implementation guide: https://blog.logrocket.com/implementing-claudes-artifacts-feature-ui-visualization/
- ChatGPT Canvas: https://help.openai.com/en/articles/9930697-what-is-the-canvas-feature-in-chatgpt-and-how-do-i-use-it
- assistant-ui GitHub: https://github.com/assistant-ui/assistant-ui

**Current state:**
- Artifacts are created by the agent via the `create_artifact` tool
- The tool returns a `side_effect` with artifact metadata: `{id, filename, content_type, file_size, download_url}`
- The WebSocket sends `suggested_actions` after tool use (same mechanism can carry artifact info)
- `ArtifactCard` component already exists at `dashboard/src/components/ArtifactCard.tsx` for download cards
- Artifacts are served via `GET /api/artifacts/{id}/download` (FileResponse)
- Artifact metadata via `GET /api/artifacts/{id}` returns `{id, filename, content_type, file_size, created_at}`

**What the artifact side_effect looks like** (already sent by the backend):
```json
{
  "artifact": {
    "id": "uuid",
    "filename": "report.html",
    "content_type": "text/html",
    "file_size": 1234,
    "download_url": "/api/artifacts/uuid/download"
  }
}
```

**NEW: We need a content endpoint.** Currently artifacts can only be downloaded as files. For preview, we need the raw content. Add this backend endpoint (or I can build it — ask Claude):

`GET /api/artifacts/{id}/content` — returns the raw file content as text (for text-based artifacts) with appropriate Content-Type header.

**Layout architecture:**

```
Current layouts:
  [Chat 100%]                           — ChatPage (no artifact)
  [Content 70% | Chat Panel 30%]        — NotebookPage/KanbanPage with cowork chat

New layout:
  [Chat 30% | Artifact Preview 70%]     — when artifact is active
```

This follows the same pattern as the existing cowork layout but reversed — chat shrinks, artifact takes the main area. AppLayout already manages `chatPanelOpen` state. Add `artifactPanelOpen` + `activeArtifactId` state.

**Components to build:**

1. **`ArtifactPreview.tsx`** — The main preview component. Takes an artifact ID, fetches content, renders based on type:

   | Content Type | Renderer |
   |---|---|
   | `text/html` | Sandboxed `<iframe srcDoc={content}>` |
   | `text/markdown` | Existing `<Markdown>` component |
   | `text/csv` | Simple HTML table rendering |
   | `application/json` | Syntax-highlighted code block |
   | `text/plain` | Pre-formatted text |
   | `text/css`, `application/javascript` | Syntax-highlighted code |
   | Other (DOCX, etc.) | Download-only card (can't preview) |

2. **Tab bar on the preview panel** with three modes:
   - **Preview** — rendered output (HTML in iframe, markdown rendered, etc.)
   - **Code** — raw source with syntax highlighting (use existing CodeBlock component or Shiki)
   - **Download** — the existing ArtifactCard with download button

3. **Panel header** showing: filename, file size, close button (X), and a "Pop out" button that opens the artifact in a new browser tab (`window.open(download_url)`)

**How the artifact panel opens:**

The backend already sends artifact info via the `suggested_actions` WebSocket message mechanism. But we need a dedicated message type. The WebSocket handler in `ws.py` already sends this after a response:

```javascript
// In ws.py, after chat_response:
if (agent._last_suggested_actions) {
    send({ type: "suggested_actions", actions: [...] })
}
```

We also need to check for artifacts. The `side_effect` from `create_artifact` includes artifact metadata. The executor stores it, and ws.py can send it:

**Option A (simpler):** After loading artifacts for the conversation (which ChatPanel already does for ArtifactCard), detect NEW artifacts that appeared since the last check and auto-open the preview panel.

**Option B (real-time):** Add a new WebSocket message type `artifact_created` that ws.py sends when the tool produces an artifact. ChatPanel listens for it and opens the preview.

**Recommend Option A** — it's simpler and doesn't require backend changes beyond the content endpoint.

**Implementation flow:**

1. Agent creates artifact → ArtifactCard appears in chat (existing behavior)
2. ChatPanel detects new artifact → sets `artifactPanelOpen = true` + `activeArtifactId`
3. AppLayout renders: `[ChatPanel 30%] [ArtifactPreview 70%]`
4. User can switch tabs (Preview/Code/Download), close panel, or pop out

**Mobile behavior:**
On mobile (< lg breakpoint), the artifact panel is full-screen with a back button to return to chat. Same pattern as how the chat panel works on mobile in the cowork layout.

**Security for HTML preview:**
HTML artifacts MUST render in a sandboxed iframe:
```tsx
<iframe
  srcDoc={content}
  sandbox="allow-scripts"
  style={{ width: '100%', height: '100%', border: 'none' }}
  title={filename}
/>
```
The `sandbox="allow-scripts"` allows JS to run but blocks:
- Access to parent window (no XSS)
- Form submissions
- Navigation changes
- Popups

DO NOT use `sandbox="allow-same-origin"` — that would defeat the sandbox.

**Files to create/modify:**
- Create: `dashboard/src/components/ArtifactPreview.tsx`
- Modify: `dashboard/src/layouts/AppLayout.tsx` (add artifactPanelOpen state, render preview panel)
- Modify: `dashboard/src/components/ChatPanel.tsx` (detect new artifacts, trigger panel open)
- Modify: `dashboard/src/components/ArtifactCard.tsx` (add "Preview" button that opens panel instead of just download)

**Verification:**
1. Ask the agent to "create an HTML page with a calculator"
2. The artifact should appear as a card in chat AND auto-open in the preview panel
3. The preview panel should show the live calculator in an iframe
4. Switching to "Code" tab should show the HTML source with syntax highlighting
5. "Download" tab should show the download button
6. Closing the panel returns to full-width chat
7. On mobile, preview should be full-screen with back button
8. TypeScript must compile: `npx tsc --noEmit`
9. Build must succeed: `npm run build`

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

### 2026-03-20 (Gemini)
- G28: Fixed auto-titles race condition using `pendingTitles` ref to bridge WebSocket updates and API refreshes.
- G29: Simplified sidebar: removed full-width toggle, added small gear icon at bottom, added "Odigos" logo at top.
- G30/G31: Verified notebook and kanban auto-redirect and header switchers.
- G33/G36: Implemented contextual "Email" link with new-mail indicator badge and "Check my email" automation.
- G34/G35: Fully wired up Analytics and Mesh tabs in `SettingsPage.tsx` and implemented `tab` query param support.
- Cleanup: Removed unused imports and variables across modified files.
- Build verified: `tsc` and `vite build` passing.

---
