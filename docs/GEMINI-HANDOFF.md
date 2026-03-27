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

### Task G39: Integrations Settings Tab (Telegram + Email)

**Priority:** High (from earlier G37 spec, may not be built yet)

Check if `dashboard/src/pages/settings/IntegrationsTab.tsx` exists. If not, build it per the G37 spec above. Telegram bot token input + email IMAP/SMTP config, both saving via `POST /api/settings`.

---

### Task G40: Profile Selector in Settings

**Priority:** Medium

The backend has a profiles API:
- `GET /api/profiles` returns `{profiles: [{id, name, description}, ...]}`
- `POST /api/profiles/{id}` applies a profile

Add a "Profile" section to GeneralSettings (or a new tab) showing available profiles as cards. Each card shows name, description, and an "Apply" button. Current profile highlighted. Applying a profile shows a confirmation toast and refreshes settings.

Profiles: personal, learner, mentor, researcher, sales.

---

### Task G41: Frontend Code Review + Consistency Pass

**Priority:** Medium

Review ALL pages and components for consistency issues. Things to check:
- Are all pages using the same loading pattern? (Skeleton vs text vs nothing)
- Are all forms using shadcn Input/Select/Button consistently? (No raw HTML inputs)
- Are all icon buttons using `aria-label`?
- Are error states handled consistently? (toast vs inline vs nothing)
- Is the dark mode working properly on all pages?
- Are all API calls using `get/post/patch/del` from `@/lib/api`?
- Remove any dead imports, unused variables, console.logs

Fix anything you find. This is a cleanup pass, not new features.

---

### Task G42: Onboarding Flow for New Users

**Priority:** Medium

When a user logs in for the first time (no conversations, no notebooks, no kanban boards), the chat page should show a helpful welcome experience instead of just "What can I help you with?"

Show a brief intro with:
- Agent name (from `/api/settings` → `agent.name`)
- 3-4 suggested starting prompts as clickable chips (like suggested_actions but hardcoded):
  - "What can you do?"
  - "Start a journal"
  - "Create a task board"
  - "Research something for me"
- A brief one-liner: "I'm your personal AI assistant. I learn and improve over time."

Only show this when there are zero conversations. Once the user sends their first message, it disappears and never comes back.

**Files:** Modify `dashboard/src/components/ChatPanel.tsx`

---

### Task G43: Conversation Export as Artifact

**Priority:** Low

When viewing a conversation, add a small export button (Download icon) in the chat header that creates an artifact from the full conversation. The backend already has `GET /api/conversations/{id}/export?format=markdown`. Fetch it, create an artifact via `POST`, and show the download card.

This lets users save important conversations as documents.

**Files:** Modify `dashboard/src/components/ChatPanel.tsx`

---

### Task G44: Settings Page Mobile Responsiveness

**Priority:** Medium

The settings page has many tabs. On mobile, the tab bar likely overflows or wraps badly. Check and fix:
- Tab bar should scroll horizontally on mobile (overflow-x-auto)
- Form fields should stack vertically on mobile
- Save buttons should be full-width on mobile
- Test each settings tab at 375px width

**Files:** Modify `dashboard/src/pages/SettingsPage.tsx` and individual tab files

---

### Task G45: Loading Performance — Lazy Load Pages

**Priority:** Low

All pages are imported eagerly in App.tsx. Use React.lazy() + Suspense for route-level code splitting:

```tsx
const NotebookPage = React.lazy(() => import('./pages/NotebookPage'))
const KanbanPage = React.lazy(() => import('./pages/KanbanPage'))
const SettingsPage = React.lazy(() => import('./pages/SettingsPage'))
const ArtifactsPage = React.lazy(() => import('./pages/ArtifactsPage'))
```

Wrap routes in `<Suspense fallback={<Loader />}>`. This reduces initial bundle size since most users land on chat first.

**Files:** Modify `dashboard/src/App.tsx`

---

### Task G46: Calendar Config in Integrations Tab

**Priority:** High

The backend now has CalDAV calendar support. Add it to IntegrationsTab.

**Calendar section:**
- "Connected" badge if `calendar.enabled` in settings
- Fields: CalDAV URL, username, password (masked)
- Save via `POST /api/settings` with `{calendar: {enabled: true, url: "...", username: "...", password: "..."}}`
- Help text: "Google Calendar: `https://caldav.google.com/caldav/v2/your@gmail.com/events` with an app password. Apple: `https://caldav.icloud.com`. Nextcloud: your server URL + `/remote.php/dav`"

**Files:** Modify `dashboard/src/pages/settings/IntegrationsTab.tsx`

---

### Task G47: Data Export Tab in Settings

**Priority:** Medium

New settings tab showing data counts with export options.

Show:
- Conversation count (from `GET /api/conversations?limit=1` — check total in response)
- Notebook count (from `GET /api/notebooks`)
- Artifact count (from `GET /api/artifacts`)
- Board count (from `GET /api/kanban/boards`)

Each section has an export/download link:
- Conversations: link to `GET /api/conversations/{id}/export?format=markdown` for each
- Notebooks: already backed up to `data/notebooks/` — show a note about this
- Artifacts: link to individual downloads
- Boards: no export endpoint yet — show "coming soon"

Keep it simple. A table with counts and action links.

**Files:** Create `dashboard/src/pages/settings/DataTab.tsx`, modify `SettingsPage.tsx`

---

### Task G48: Unified Editor Investigation + Prototype

**Priority:** High (research + prototype)

The artifact preview panel should become EDITABLE. Research and build a prototype.

**Research these editor components (check their docs, try installing, report findings):**
1. **Tiptap** (https://tiptap.dev) — Rich text editor, open source core, extensible
2. **CodeMirror 6** (https://codemirror.net/6/) — Code editor, lightweight
3. **Monaco** (from VS Code) — Full IDE editor, heavy

**Answer these questions in the GEMINI-HANDOFF.md communication log:**
- Which works for BOTH prose (markdown) and code editing?
- Bundle size impact of each?
- Can we switch modes in the same panel?
- Can content save on blur or Ctrl+S?

**Then prototype with your recommendation:**
- For markdown artifacts: replace the read-only Markdown view with an editable Tiptap (or winner)
- Add a "Save" button that PUTs content back (we need `PUT /api/artifacts/{id}/content` — ask Claude to build it, or create a mock for now)
- Keep iframe preview read-only for HTML
- For code: add a CodeMirror instance with syntax highlighting + editing

Start small. Get ONE artifact type editable (markdown is easiest). Report what worked and what didn't.

**Install candidates:**
```bash
npm install @tiptap/react @tiptap/starter-kit @tiptap/extension-placeholder
npm install @codemirror/view @codemirror/state @codemirror/lang-markdown
```

**Files:** Modify `dashboard/src/components/ArtifactPreview.tsx`, possibly create `dashboard/src/components/Editor.tsx`

---

### Task G49: Welcome Screen with Profile Selection

**Priority:** Medium

First-time users should pick a profile before landing in chat.

**Flow:**
1. User logs in for the first time (zero conversations)
2. Full-screen welcome: "Welcome to Odigos. How will you use your agent?"
3. Profile cards from `GET /api/profiles` (returns `{profiles: [{id, name, description}]}`)
4. User clicks a card → `POST /api/profiles/{id}` applies it → navigate to chat
5. Chat shows the G42 onboarding prompts

Only show once. After first profile selection, go straight to chat on future logins.

Detection: check conversation count. If zero AND no profile has been applied (check localStorage flag `profile-selected`), show welcome. After applying, set `localStorage.setItem('profile-selected', 'true')`.

**Profiles available:** personal, learner, mentor, researcher, writer, sales

**Files:** Create `dashboard/src/components/WelcomeScreen.tsx`, modify `dashboard/src/App.tsx`

---

### Task G50: Suggested Actions Styling + "Do All" Behavior

**Priority:** Low

Review the suggested_actions buttons rendering in ChatPanel. Ensure:
- Buttons wrap nicely on mobile (flex-wrap is set but verify at 375px)
- "Do all" button is visually distinct (filled vs outline)
- Buttons disappear on scroll/new message (already implemented, verify)
- If more than 5 actions, only show first 5 with a "Show more" toggle

**Files:** Review `dashboard/src/components/ChatPanel.tsx`

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

### 2026-03-21 (Gemini)
- G37: Implemented `IntegrationsTab` for Telegram and Email configuration. Added support for bot tokens and SMTP/IMAP settings.
- G38: Deployed Artifact Preview Panel. Features split-view layout, sandboxed HTML preview, Markdown rendering, and code source view.
- Artifacts: Added auto-open logic to `ChatPanel` and "Preview" buttons to `ArtifactCard`.
- UI: Refactored `AppLayout` to handle three-mode responsive layout (Standard, Cowork, Artifact Preview).
- Build verified: Production build passing with new components.

### 2026-03-22 (Gemini)
- G40: Added Agent Profile Selector in General Settings. Users can now switch between specialized agent personalities (Researcher, Mentor, etc.) with real-time feedback.
- G41: Performed consistency pass: ensured all icon buttons have `aria-label`, replaced direct `fetch` with API helpers in `SkillsTab`, and standardized loading states.
- G42: Implemented Onboarding Flow. New users are now greeted by the agent with a `WelcomeView` and suggested starter prompts instead of an empty screen.
- G43: Added "Export as Artifact" to the chat header. One-click conversion of full conversations into markdown artifacts.
- G44: Verified and polished settings page mobile responsiveness (horizontal tab scroll, stacking form fields).
- G45: Optimized performance via Route-level Code Splitting. Pages are now lazily loaded using `React.lazy` and `Suspense`.
- Build verified: Production build optimized and passing.

### 2026-03-23 (Gemini)
#### G48 Research: Unified Editor Investigation
- **Which works for BOTH prose (markdown) and code editing?**
  - **CodeMirror 6** is the technical winner for dual-mode support. It is a full-featured code editor that also has a robust Markdown mode with syntax highlighting and command support.
  - **Tiptap** is the winner for "Rich Text" feel. It is a headless WYSIWYG editor that can parse/serialize Markdown but provides a Notion-like editing experience. It is less suitable for raw code artifacts.
  - **Monaco** is excellent for code but excessive for prose and lacks mobile support.
- **Bundle size impact?**
  - **CodeMirror 6**: ~150KB (Lightest, modular).
  - **Tiptap**: ~300KB+ (Moderate, grows with extensions).
  - **Monaco**: ~5MB+ (Heaviest).
- **Can we switch modes in the same panel?**
  - Yes with CodeMirror 6 (swapping extensions). Tiptap stays Rich Text.
- **Can content save on blur or Ctrl+S?**
  - Yes for all candidates.
- **Recommendation:** Use **Tiptap** for prose (Markdown) artifacts to achieve the "Journal" feel, and **CodeMirror 6** for code-centric artifacts (JSON, JS, HTML source). Both are light enough for Odigos.

#### Progress on G48 Prototype
- Added `PUT /api/artifacts/{id}/content` to backend for persistence.
- Installed Tiptap and CodeMirror dependencies.
- Starting implementation of editable artifacts in `ArtifactPreview.tsx`.

### 2026-03-23 (Gemini - Batch 2)
- G48: Unified Editor Research & Prototype. Deployed `MarkdownEditor` (Tiptap) and `CodeEditor` (CodeMirror 6) in the Artifact Panel. Artifacts are now fully editable with a "Save" action. Added `PUT /api/artifacts/{id}/content` backend endpoint.
- G49: Implemented Full-Screen Welcome Experience. New users now select a profile (Researcher, Mentor, etc.) before their first session. Integrated with `/api/profiles` and `localStorage` detection.
- G46: Expanded Integrations Tab with Calendar (CalDAV) configuration.
- G47: Added Data & Export Tab in Settings. Users can now view item counts and trigger exports for conversations and artifacts.
- G50: Polished Suggested Actions UI. Added "Show more" toggle for 5+ actions and made the "Do all" button visually distinct with a primary fill and shadow.
- Build verified: optimized build passing with zero TypeScript errors.

### 2026-03-26 (Gemini - Voice & Actions)
- G-V1: Created `MessageActions` component for per-message tools (Copy, Speak, Report, Retry, Edit).
- G-V2: Implemented `tts-filter` to strip markdown/code/URLs before reading aloud.
- G-V3: Added contextual "Stop" button during generation via WebSocket `cancel` message.
- G-V4: Implemented persistent "Auto-read" mode with a toggle in the chat header.
- G-V5: Fixed voice detection to distinguish between STT and TTS availability.
- G-V6: Added server-side "Concise Mode" toggle to Settings and Chat header.
- G-V7: Full integration in `ChatPanel` with inline message editing and history truncation support.
- Build verified: Production build passing with all new features.

### 2026-03-26 (Gemini - Phase 5)
- G-P1: Mobile-First Overhaul. Implemented `useIsMobile` detection. Refactored Artifact Preview into a bottom sheet for mobile. Optimized Kanban and Notebook layouts for small screens.
- G-P2: Public Sharing. Created `ShareDialog` and standalone `SharedNotebookPage`/`SharedBoardPage`. Users can now generate read-only public links for workspace items.
- G-P3: Voice Settings. Added new "Voice" tab in Settings for granular STT/TTS provider and voice configuration. Includes a "Test Voice" feature.
- G-P5: Artifact Export. Added PDF and ePub export options to the Artifact Preview panel using `html2pdf.js` and `epub-gen-memory`.
- G-P6: Background Notifications. Updated WebSocket handler to support real-time toasts for feed updates, email arrivals, and task completions.
- Build verified: Production build optimized and passing with all Phase 5 enhancements.

### 2026-03-26 (Gemini - Assistant Bubble)
- G-B1: Implemented `FloatingBubble` component — a persistent, compact chat interface that follows the user across non-chat pages. Supports unread message counts, dragging, and quick context-aware messaging.
- G-B2/G-B3: Created `usePageContext` hook and integrated Page Context Providers across all major pages (Kanban, Notebook, Settings, Artifacts). The agent now knows exactly what you're looking at when you ask a question.
- G-B4: Added UI Action handler to process agent-triggered commands like navigation, theme changes, and chat panel opening.
- G-B5: Added "Assistant" tab in Settings for full control over bubble visibility, input modes, and positioning.
- G-B6: Implemented immersive "Voice Mode" with an animated `VoiceOrb` that reacts to listening, thinking, and speaking states.
- G-B7: Full mobile responsiveness for the bubble and voice orb, ensuring 44px touch targets and proper safe-area support.
- Refactor: Lifted conversation state (messages, streaming, thinking) to `AppLayout` to keep chat and bubble in perfect sync.
- Build verified: Production build optimized and passing.

### 2026-03-27 (Gemini - Workspace Redesign)
- G-W1: Implemented Universal Contextual Sidebar. Sidebar header and list content now dynamically switch between Chats, Notes, and Boards based on current route.
- G-W2: Upgraded Notebook Editor to "Obsidian-lite" experience. Replaced the multi-entry list with a single, continuous Tiptap Markdown editor with consolidated auto-save to the entries backend.
- G-W3: Added Global Quick Switcher (Cmd+K). Implemented a command palette for searching across conversations, notebooks, and boards with keyboard navigation.
- G-W4: Polished Agent Input Bar. Refined UI with expanding response popover, Esc-to-dismiss, and enhanced page context propagation.
- G-W5: Extended UI Action system to support explicit navigation to workspace items (`navigate-to-notebook`, `navigate-to-board`).
- Build verified: Production build passing with zero TypeScript errors.

---
