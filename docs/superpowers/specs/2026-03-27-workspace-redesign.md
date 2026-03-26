# Workspace Redesign — Integrated Notebook Editor, Navigation, Agent Input

**Date:** 2026-03-27
**Status:** Draft

## Vision

Odigos should feel like one workspace, not separate tools. The user talks, writes, plans, and the agent is always there — orchestrating, assisting, navigating. Switching between chat, notebook, and kanban should be seamless. The agent knows where you are and can take you where you need to be.

## Core Principles

1. **Everything is one click from chat.** You can always get back.
2. **The agent travels with you.** Available on every page, but not in your face.
3. **Focus mode exists.** When writing, the agent input hides. Clean editor, nothing else.
4. **The agent orchestrates.** "Continue the story" → opens notebook, last entry. "Add to roadmap" → creates card on the right board.

---

## 1. Contextual Sidebar

The sidebar stays contextual — its content changes based on what page you're on. But it ALWAYS has a way to navigate between workspaces.

### Sidebar Header (all pages)

```
┌─────────────────┐
│ [Agent Name]    │  ← click = new chat (always)
│ ┌─┐ ┌─┐ ┌─┐   │
│ │💬│ │📝│ │📋│   │  ← workspace tabs: Chat / Notes / Boards
│ └─┘ └─┘ └─┘   │
│ ─ ─ ─ ─ ─ ─ ─ │
```

Three small icon tabs at the top of the sidebar switch the context:
- **Chat** (MessageCircle): shows conversation list (current behavior)
- **Notes** (FileText): shows notebook list
- **Boards** (Columns3): shows kanban board list

Clicking a tab switches the sidebar content AND navigates to that workspace. The active tab is highlighted. This replaces the "Journal / Board / Documents" quick links at the bottom of chat input.

### Sidebar Footer (all pages)

```
│ ─ ─ ─ ─ ─ ─ ─ │
│ ⚙ Settings      │  ← or 💬 Chat when on settings
└─────────────────┘
```

Same as current — settings gear, swaps to chat bubble when on settings.

### Sidebar Content by Page

**Chat page:** Conversation list (current behavior, unchanged)

**Notebook page:**
```
│ MY NOTEBOOKS    │
│  Daily Journal  │  ← click to switch notebook
│  Meeting Notes  │
│  Research       │
│  + New notebook │
│                 │
│ ENTRIES         │  ← entries for active notebook
│  Mar 27         │  ← click to jump to entry in editor
│  Mar 26         │
│  Mar 25         │
│                 │
│ ┌─────────────┐ │
│ │ 🔗 Share    │ │  ← share button for active notebook
│ │ 🗑 Delete   │ │
│ └─────────────┘ │
```

**Kanban page:**
```
│ MY BOARDS       │
│  Project Alpha  │  ← click to switch board
│  Sprint 3       │
│  Roadmap        │
│  + New board    │
│                 │
│ FILTERS         │  ← optional: filter cards by priority/assignee
│  ○ All          │
│  ○ High only    │
│                 │
│ ┌─────────────┐ │
│ │ 🔗 Share    │ │
│ │ 🗑 Delete   │ │
│ └─────────────┘ │
```

**Settings page:** Settings section list (current behavior, unchanged)

---

## 2. Notebook Editor (Obsidian-lite)

### Current State (problems)
- Entry list with timestamps and "general - read" labels
- "Ask Agent" button cluttering the interface
- Textarea for adding entries, not a real editor
- No way to edit existing entries inline
- Feels like a log, not a writing tool

### New Design

The notebook page becomes a full-screen markdown editor.

```
┌─────────────────┬──────────────────────────────────────────┐
│ [Agent Name]    │                                          │
│ 💬 📝 📋       │  Daily Journal                           │
│                 │  ─────────────────────────────────────── │
│ MY NOTEBOOKS    │                                          │
│ > Daily Journal │  March 27, 2026                          │
│   Meeting Notes │                                          │
│                 │  Today I worked on the voice integration  │
│ ENTRIES         │  for Odigos. The STT system is now       │
│  > Mar 27  ←   │  working with Groq Whisper and the       │
│    Mar 26      │  hallucination filtering catches most     │
│    Mar 25      │  false positives.                         │
│                 │                                          │
│                 │  ## Next Steps                            │
│                 │  - Workspace redesign                     │
│                 │  - Deploy to testers                      │
│                 │                                          │
│                 │  ---                                      │
│                 │  March 26, 2026                           │
│                 │                                          │
│                 │  Big day. Shipped voice mode, message     │
│                 │  actions, floating bubble...              │
│                 │                                          │
│                 ├──────────────────────────────────────────│
│                 │ [Agent Name] type / or click to ask...   │
│ 🔗 Share       │  ← dismissable agent input               │
│ ⚙ Settings     │                                          │
└─────────────────┴──────────────────────────────────────────┘
```

### Editor Behavior

**Single continuous document:** Entries are rendered as one continuous markdown document separated by date headers. No separate "entry cards." The user writes in a flowing document like Obsidian or Notion.

**New entries:** Typing at the bottom creates a new entry. A subtle date divider auto-inserts when the day changes. No "Add Entry" button needed — just write.

**Editing:** Click anywhere in any entry to edit it inline. The editor is always live — changes auto-save after a short debounce (1-2 seconds of inactivity).

**Markdown support:** Full markdown rendering in-place (like Obsidian's live preview mode). Headings, bold, lists, code blocks, links — all rendered as you type.

**Title:** Editable at the top. Click to rename.

### Components

Reuse the existing `MarkdownEditor` component from the artifact system. It already supports Tiptap for rich text and CodeMirror for code — just need to wire it for notebook entries.

### API Changes Needed

**Auto-save endpoint:**
```
PATCH /api/notebooks/{id}/entries/{entry_id}
Body: { "content": "updated text" }
```
This already exists. The frontend just needs to call it on debounced changes.

**Create entry on typing:**
When the user types below the last entry, auto-create a new entry via:
```
POST /api/notebooks/{id}/entries
Body: { "content": "new text", "entry_type": "user" }
```

---

## 3. Agent Input Bar (persistent, dismissable)

A thin input bar at the bottom of every workspace page. Same agent, same WebSocket, same conversation — just a different UI context.

### States

**Visible (default):**
```
┌──────────────────────────────────────────┐
│ [Agent Name] type / or click to ask...   │
└──────────────────────────────────────────┘
```

Small, subtle, bottom of the page. Shows the agent name as a label. Click or type `/` to focus. Has a mic button for voice.

**Focused:**
```
┌──────────────────────────────────────────┐
│ Ask about this notebook...          🎤 ↑ │
└──────────────────────────────────────────┘
```

Textarea expands slightly. Placeholder shows context ("Ask about this notebook..." / "Ask about this board..."). Send button appears.

**Hidden (focus mode):**
Press `Esc` while in the editor, or click a "focus" button. The input bar slides away. The full screen is the editor.

To bring it back: press `/` or click the agent name in the sidebar header.

**Response:**
When the agent responds to a workspace query, the response shows as a temporary floating panel above the input bar (like a tooltip/popover). It doesn't navigate to chat — the response is inline. If it's a long response or the user wants to continue the conversation, a "Continue in chat" link opens the cowork chat panel.

### Context

Every message sent from the workspace input bar includes page context:
```json
{
  "type": "chat",
  "content": "summarize what I wrote today",
  "context": {
    "page": "notebook",
    "page_id": "nb-abc123",
    "page_title": "Daily Journal",
    "visible_data": "3 entries today. Latest: 'Workspace redesign spec...'"
  }
}
```

The agent receives this in the system prompt and can respond with actions.

---

## 4. Agent Orchestration Actions

The agent can respond with UI actions (already implemented in `ws.py`). Expanding the action set:

### Current Actions
- `navigate` — go to a URL
- `refresh` — reload current page
- `theme` — switch dark/light

### New Actions
- `open_notebook` — navigate to a specific notebook and optionally a specific entry
  ```json
  {"action": "navigate", "to": "/notebooks/abc123"}
  ```
- `open_board` — navigate to a specific kanban board
  ```json
  {"action": "navigate", "to": "/kanban/def456"}
  ```
- `create_and_navigate` — create a new item and navigate to it
  ```json
  {"action": "create", "type": "notebook", "title": "Meeting Notes"}
  ```
  Frontend handles the POST + navigation.
- `focus_entry` — scroll to a specific entry in the notebook
  ```json
  {"action": "focus_entry", "entry_id": "entry-xyz"}
  ```

### Example Flows

**"Continue writing the story":**
1. Agent checks context — finds a notebook with recent story entries
2. Responds: "Opening your story notebook..." + `{"action": "navigate", "to": "/notebooks/story-id"}`
3. Frontend navigates, notebook opens on the latest entry
4. User starts writing

**"Add that to the Roadmap":**
1. Agent has the current conversation context
2. Creates a card on the Roadmap board via its kanban tools
3. Responds: "Added to Roadmap board" + `{"action": "navigate", "to": "/kanban/roadmap-id"}`
4. User sees the new card

**"What's on my board?":**
1. User is on any page, types into the agent input
2. Agent reads board context, summarizes
3. Response shows as inline popover — no navigation needed

---

## 5. Kanban Improvements

Apply the same patterns as the notebook redesign:

### Sidebar
Board list in sidebar (as described in Section 1). Active board highlighted. Switch boards from sidebar.

### Agent Input
Same persistent agent input bar at bottom. "Ask about this board..."

### Missing Features
- Inline card editing (click card to edit title/description)
- Card detail panel (click card → slide-out panel with full description, due date, priority)
- Drag should work on mobile (already partially done with column switcher)

---

## 6. Focus Mode

A global toggle that hides all chrome except the content:

- **In notebook:** Editor fills the entire screen. No sidebar, no agent input, no header.
- **In kanban:** Board fills the screen.
- **Exit:** Press `Esc`, or move mouse to top/bottom edge to reveal controls.

Keyboard shortcut: `Cmd+.` or `Ctrl+.` to toggle focus mode.

---

## 7. Quick Links Removal

The quick links at the bottom of the chat input (Journal, Board, Documents, Voice, Email) are replaced by the workspace tabs in the sidebar. Remove them from ChatPanel.

---

## 8. Implementation Split

### Backend (Claude) — minimal
1. No new endpoints needed — notebook/kanban CRUD already exists
2. Extend action handling in `ws.py` for `create_and_navigate` and `focus_entry`
3. Add notebook/board search tool so agent can find items by name ("open my story notebook")

### Frontend (Gemini) — the bulk of the work

**Phase 1: Sidebar + Navigation**
1. Workspace tabs (Chat/Notes/Boards icons) in sidebar header
2. Contextual sidebar content based on active tab/route
3. Remove quick links from ChatPanel
4. Navigation always works — can get to chat from anywhere

**Phase 2: Notebook Editor**
1. Replace entry list with continuous markdown editor
2. Entries rendered as one flowing document with date separators
3. Inline editing with auto-save (debounced PATCH)
4. Auto-create new entry when typing at bottom
5. Reuse MarkdownEditor from artifact system
6. Editable title at top
7. Entry list in sidebar for quick jumping

**Phase 3: Agent Input Bar**
1. Persistent input at bottom of notebook and kanban pages
2. Shows agent name, placeholder with context
3. Sends messages via existing WebSocket with page context
4. Inline response popover (not navigation to chat)
5. "Continue in chat" link for long conversations
6. Dismissable with Esc, restorable with / or click
7. Mic button for voice mode

**Phase 4: Focus Mode**
1. Cmd+. toggle to hide all chrome
2. Edge hover to reveal controls
3. Esc to exit

**Phase 5: Kanban Polish**
1. Sidebar board list following notebook pattern
2. Agent input bar on kanban page
3. Inline card editing
4. Card detail slide-out panel

### Estimated Gemini Tasks
- G-W1: Sidebar workspace tabs + contextual content switching
- G-W2: Notebook page rewrite — continuous editor, auto-save, date separators
- G-W3: Agent input bar component (shared between notebook + kanban)
- G-W4: Inline response popover for agent answers
- G-W5: Focus mode toggle
- G-W6: Kanban sidebar + agent input
- G-W7: Remove quick links, clean up navigation
- G-W8: Mobile adaptations for all new patterns

---

## 9. What This Replaces

| Current | New |
|---------|-----|
| Quick links (Journal/Board/etc) at bottom of chat | Workspace tabs in sidebar |
| Separate notebook page with entry list | Continuous markdown editor |
| "general - read" labels on notebooks | Nothing — clean editor |
| "Ask Agent" button on notebook | Persistent agent input bar |
| No way back to chat from notebook/kanban | Workspace tabs always visible |
| Floating bubble (removed) | Agent input bar on every page |
| Separate disconnected tools | One integrated workspace |

---

## 10. What NOT to Change

- Chat page — works well, don't touch
- Settings page — recently redesigned, works
- Artifact panel — already integrates with chat
- Voice mode — works, just needs to work from agent input bar too
- Backend APIs — all exist, minimal changes
- WebSocket — already handles page context and actions
