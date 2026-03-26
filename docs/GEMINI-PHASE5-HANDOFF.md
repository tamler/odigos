# Gemini Phase 5 Handoff — Mobile, Sharing, Voice Settings, Notifications

## Overview

6 feature areas, prioritized. All backend APIs will be implemented before Gemini starts.

---

## G-P1: Mobile-First Responsive Overhaul (PRIORITY 1)

The layout already has basic mobile support (hamburger menu, `lg:` breakpoints) but the chat experience on mobile is not good. The artifact panel, cowork chat panel, and notebooks/kanban need proper mobile treatment.

### Goals
- Chat is the primary mobile experience — full screen, no wasted space
- Artifact panel slides up as a bottom sheet on mobile (not a side panel)
- Cowork chat panel is full-screen overlay on mobile (already partially done)
- Notebook and Kanban pages work on mobile with touch-friendly sizing
- All touch targets are minimum 44px
- No horizontal scroll anywhere on mobile

### Files to Modify
- `dashboard/src/layouts/AppLayout.tsx` — main layout with sidebar, chat, artifact panel
- `dashboard/src/components/ChatPanel.tsx` — chat input area, message list
- `dashboard/src/components/ArtifactPreview.tsx` — artifact panel
- `dashboard/src/pages/KanbanPage.tsx` — kanban board
- `dashboard/src/pages/NotebookPage.tsx` — notebook editor
- `dashboard/src/pages/SettingsPage.tsx` — settings tabs
- `dashboard/src/index.css` — any global mobile styles needed

### Specific Changes

**AppLayout.tsx:**
- Mobile top bar (line 235): already exists, keep it
- Artifact panel on mobile: instead of side-by-side, render as a bottom sheet that slides up from the bottom, covering ~70% of the screen. User can drag to dismiss or tap a close button.
- When artifact panel is open on mobile, chat shrinks to show last few messages above the sheet (like iMessage with keyboard open)
- Chat panel in cowork mode on mobile: already renders as `fixed inset-0 z-50` — this is fine

**ChatPanel.tsx:**
- Input area: on mobile, the textarea + buttons should be pinned to the bottom with `pb-safe` (safe area inset for iOS)
- Message bubbles: reduce horizontal padding on mobile (`px-3` instead of `px-5`)
- Header toggles (auto-read, concise): collapse into a `...` menu on mobile to save space
- File upload: touch-friendly, show camera option on mobile

**KanbanPage.tsx:**
- Columns should stack vertically on mobile (not horizontal scroll)
- Or: horizontal scroll with snap points (each column is full-width)
- Cards: larger touch targets, swipe to move between columns

**NotebookPage.tsx:**
- Editor should be full-width on mobile
- Entry list as a collapsible section or separate tab

**SettingsPage.tsx:**
- Tab navigation: horizontal scroll on mobile, or convert to accordion sections
- Form inputs: full-width, larger touch targets

### Breakpoints
- `sm:` (640px) — phones
- `md:` (768px) — tablets
- `lg:` (1024px) — desktop (existing breakpoint for sidebar)

### Testing
- [ ] Test on iPhone Safari (viewport 390px)
- [ ] Test on Android Chrome (viewport 360px)
- [ ] Chat input doesn't get hidden behind keyboard
- [ ] Artifact panel as bottom sheet works with swipe
- [ ] Kanban columns scrollable on mobile
- [ ] No horizontal overflow on any page
- [ ] All buttons/links minimum 44px touch target
- [ ] Safe area insets work on notched phones

---

## G-P2: Shared Notebooks & Kanban Boards

Two sharing modes for notebooks and kanban boards.

### Mode 1: Public Link Sharing (read-only)
- User clicks "Share" on a notebook or kanban board
- System generates a share token (random 16-char hex)
- Returns a URL: `/shared/notebook/{token}` or `/shared/board/{token}`
- Anyone with the link can view it — no login required
- Read-only: viewer sees content but cannot edit
- Owner can revoke the share link

### Mode 2: Mesh Agent Sharing
- Toggle `shared: true` on a board/notebook
- Other agents on the mesh can read it via the mesh API
- Already partially supported by mesh infrastructure

### Backend API (already implemented when you start)

**Notebooks:**
```
POST /api/notebooks/{id}/share → { "share_token": "abc123...", "url": "/shared/notebook/abc123..." }
DELETE /api/notebooks/{id}/share → revokes the share link
GET /shared/notebook/{token} → returns notebook data (NO AUTH REQUIRED)
```

**Kanban:**
```
POST /api/kanban/boards/{id}/share → { "share_token": "abc123...", "url": "/shared/board/abc123..." }
DELETE /api/kanban/boards/{id}/share → revokes the share link
GET /shared/board/{token} → returns board data with columns and cards (NO AUTH REQUIRED)
```

### Frontend Changes

**Share Button:**
Add a "Share" button to:
- Notebook header (next to title)
- Kanban board header

Clicking "Share" calls the POST endpoint, then shows a dialog with:
- The share URL (copyable with a "Copy Link" button)
- A "Revoke" button to delete the share link
- If already shared, show the existing URL

**Icons:** `Share2` (lucide) for the share button, `Globe` for indicating shared status.

**Shared View Pages:**
Create two new route pages:
- `dashboard/src/pages/SharedNotebookPage.tsx` — renders notebook entries read-only
- `dashboard/src/pages/SharedBoardPage.tsx` — renders kanban board read-only

These pages:
- Have NO sidebar, NO auth, NO navigation — just the content with a simple header showing the title
- Show "Shared by [agent name]" at the top
- Clean, minimal design — white background, centered content
- Notebook: renders entries as markdown with timestamps
- Kanban: renders columns and cards in read-only layout (no drag)
- If token is invalid, show "This shared link is no longer available"

**Routes:**
Add to `App.tsx`:
```tsx
<Route path="/shared/notebook/:token" element={<SharedNotebookPage />} />
<Route path="/shared/board/:token" element={<SharedBoardPage />} />
```

These routes should NOT be inside the AppLayout — they are standalone pages.

### Files to Create
- `dashboard/src/pages/SharedNotebookPage.tsx`
- `dashboard/src/pages/SharedBoardPage.tsx`

### Files to Modify
- `dashboard/src/pages/NotebookPage.tsx` — add Share button
- `dashboard/src/pages/KanbanPage.tsx` — add Share button
- `dashboard/src/components/kanban.tsx` — share dialog
- `dashboard/src/App.tsx` — add shared routes

### Testing
- [ ] Share button generates link and shows in dialog
- [ ] Copy link button works
- [ ] Shared notebook page renders entries read-only
- [ ] Shared board page renders columns and cards
- [ ] Invalid token shows error message
- [ ] Revoke removes the share link
- [ ] Shared pages work without login
- [ ] Shared pages are mobile-friendly

---

## G-P3: Voice Settings UI

Add a Voice section to the Settings page.

### Settings Available (from GET /api/settings)
```json
{
  "voice": {
    "stt_provider": "groq",      // "groq", "local", or "disabled"
    "tts_provider": "edge",      // "edge", "local", or "disabled"
    "tts_voice": "en-US-AriaNeural",
    "groq_model": "whisper-large-v3-turbo"
  }
}
```

### UI Design

Create `dashboard/src/pages/settings/VoiceTab.tsx`:

**Speech-to-Text (STT) Section:**
- Provider dropdown: Groq / Local / Disabled
- Model field (only when provider is "groq"): text input, default "whisper-large-v3-turbo"
- Cost note: "Groq Whisper: ~$0.04/hour of audio"

**Text-to-Speech (TTS) Section:**
- Provider dropdown: Edge (Free) / Local / Disabled
- Voice selector (only when provider is "edge"): dropdown with common edge-tts voices:
  - en-US-AriaNeural (default, female)
  - en-US-GuyNeural (male)
  - en-US-JennyNeural (female)
  - en-GB-SoniaNeural (British female)
  - en-GB-RyanNeural (British male)
  - en-AU-NatashaNeural (Australian female)
- "Test" button next to voice selector — plays a short sample via `/api/audio/speak?text=Hello, I am your AI assistant.`

**Save** button at bottom — POST to `/api/settings` with `{ "voice": { ... } }` (note: voice is not currently in the SettingsUpdate model, see Backend Notes below).

### Backend Notes
The SettingsUpdate model in `odigos/api/settings.py` needs `voice: dict | None = None` added. This will be done before you start.

### Files to Create
- `dashboard/src/pages/settings/VoiceTab.tsx`

### Files to Modify
- `dashboard/src/pages/SettingsPage.tsx` — add Voice tab

### Testing
- [ ] Voice tab appears in settings
- [ ] STT provider dropdown works
- [ ] TTS provider dropdown works
- [ ] Voice selector appears only when TTS is "edge"
- [ ] Test button plays audio sample
- [ ] Settings save correctly
- [ ] Disabling TTS hides speak icons in chat (verify with page reload)

---

## G-P4: Settings Page Voice Section Update

(Merged into G-P3 above — this was a duplicate)

---

## G-P5: PDF & ePub Artifact Export

Add export buttons to the artifact preview panel for PDF and ePub formats.

### Approach
Use browser-side generation — no backend changes needed.
- **PDF:** Use `html2pdf.js` or `jspdf` + `html2canvas`
- **ePub:** Use `epub-gen-memory` (browser-compatible ePub generator)

### UI
Add export buttons to `ArtifactPreview.tsx`:
- Current: Download button (downloads raw file)
- New: Dropdown with "Download", "Export as PDF", "Export as ePub"

### PDF Export Flow
1. Render the artifact content as styled HTML (same as preview)
2. Convert to PDF using html2pdf.js
3. Download with filename `{artifact-title}.pdf`

### ePub Export Flow
1. Extract title and content from artifact
2. Generate ePub with epub-gen-memory
3. Download with filename `{artifact-title}.epub`

### Dependencies to Install
```bash
cd dashboard && npm install html2pdf.js epub-gen-memory
```

### Files to Modify
- `dashboard/src/components/ArtifactPreview.tsx` — add export dropdown

### Testing
- [ ] PDF export generates readable PDF
- [ ] ePub export generates valid ePub (open in Books app)
- [ ] Markdown formatting preserved in both formats
- [ ] Long documents don't crash the export
- [ ] Export buttons visible on mobile

---

## G-P6: Background Task Notifications

When the agent completes background tasks, show subtle toast notifications.

### Current Behavior
The WebSocket already sends `notification` messages (see `AppLayout.tsx` line 98). These show as toasts. But many background operations (feed checks, email checks, auto-title) don't send notifications.

### Changes Needed

**Frontend only** — add handlers for new WebSocket message types:

In `AppLayout.tsx` WebSocket message handler, add:
```typescript
if (msg.type === 'feed_update') {
  toast.info(`New feed items from ${msg.source || 'RSS feed'}`, { duration: 4000 })
}
if (msg.type === 'email_received') {
  setHasNewEmail(true)
  toast.info(`New email: ${msg.subject || 'New message'}`, { duration: 5000 })
}
if (msg.type === 'task_completed') {
  toast.success(`Completed: ${msg.task || 'Background task'}`, { duration: 3000 })
}
```

These message types will be sent by the backend when relevant events occur. The backend changes are separate — for now, just add the handlers so they're ready.

### Notification Style
- Use `sonner` toast (already in use)
- Subtle: `duration: 3000-5000ms`, no persistent notifications
- Info level for most, success for completions
- Error level for failures (already handled)

### Files to Modify
- `dashboard/src/layouts/AppLayout.tsx` — add message handlers

### Testing
- [ ] Feed update toast appears (test by sending mock WebSocket message)
- [ ] Email notification shows and sets the email badge
- [ ] Task completion toast appears
- [ ] Notifications don't stack excessively

---

## G-P7: Settings Layout Redesign + Agent Name

The Settings page has too many tabs crammed horizontally. Redesign to use the sidebar for section navigation, matching the chat/artifact layout pattern.

### Layout Change

When the user navigates to `/settings`:
- The **left sidebar** replaces the conversation list with settings section links (General, Voice, LLM, Budget, Mesh, Email, Integrations, Plugins, Evolution, etc.)
- The **main content area** renders the selected settings section at full width
- The **"Odigos" brand name** in the upper-left becomes the **agent's name** (from `GET /api/settings` → `agent.name`). This applies globally, not just in settings.
- The **gear icon** at the bottom of the sidebar becomes a **chat bubble** (`MessageCircle` from lucide) when in Settings — clicking it returns to chat
- When back in chat view, the icon returns to the gear (`Settings` icon)

### Sidebar Sections

Replace the horizontal tabs with sidebar links. Current tabs from `SettingsPage.tsx`:
- General
- Voice (new from G-P3)
- Integrations
- Mesh
- Plugins
- Evolution
- Analytics
- Data
- Documents
- Prompts
- Account

Each section link: icon + label, highlighted when active. Same styling as conversation list items.

### Agent Name

The "Odigos" text in the sidebar header (`AppLayout.tsx` line 251) should be replaced with the agent's configured name:

```typescript
// Fetch agent name on mount (already available from settings)
const [agentName, setAgentName] = useState('Odigos')
// In the settings fetch:
get('/api/settings').then(s => setAgentName(s.agent?.name || 'Odigos'))
```

Display `agentName` instead of hardcoded "Odigos" in the sidebar header. This applies on ALL pages, not just settings.

### Navigation Icon Swap

In the sidebar footer, the Settings gear icon should be context-aware:

```tsx
// When on /settings route:
<MessageCircle /> → navigates to /

// When on any other route:
<Settings /> → navigates to /settings
```

Use `useLocation()` to detect current route:
```typescript
const location = useLocation()
const isSettings = location.pathname.startsWith('/settings')
```

### Mobile Behavior
- On mobile, settings sections show as a scrollable list (like the conversation list)
- Selecting a section shows the content full-screen with a back arrow
- Same pattern as any mobile drill-down navigation

### Files to Modify
- `dashboard/src/layouts/AppLayout.tsx` — sidebar context switching, agent name, icon swap
- `dashboard/src/pages/SettingsPage.tsx` — remove horizontal tabs, render only the active section content
- `dashboard/src/App.tsx` — routing may need adjustment for `/settings/:section` pattern

### Testing
- [ ] Settings sections appear in sidebar when on /settings
- [ ] Clicking a section shows its content in main area
- [ ] Gear icon becomes chat bubble on settings page
- [ ] Chat bubble returns to chat view
- [ ] Agent name shows instead of "Odigos" (configure a custom name to verify)
- [ ] Conversation list returns when navigating back to chat
- [ ] Mobile: sections as list, drill-down to content
- [ ] Back navigation works correctly on mobile

---

## Implementation Order

1. **G-P7: Settings layout redesign** (highest impact, changes interaction model)
2. **G-P1: Mobile responsive** (touches most files, do after layout is settled)
3. **G-P2: Shared notebooks/kanban** (new feature, new pages)
4. **G-P3: Voice settings UI** (settings page — now renders in new layout)
5. **G-P5: PDF/ePub export** (artifact enhancement)
6. **G-P6: Notifications** (small, quick win)

## Backend Tasks (Claude will do before Gemini starts)

1. **Share endpoints** — DONE
2. **Migration** — DONE (041_sharing.sql)
3. **Voice in SettingsUpdate** — DONE
4. **Mesh sharing** — expose shared boards/notebooks via mesh API
