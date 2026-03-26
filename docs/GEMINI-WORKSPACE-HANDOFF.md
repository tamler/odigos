# Gemini Workspace Redesign Handoff

## Overview

Transform Odigos from separate tools into one integrated workspace. The sidebar becomes the universal navigator, notebooks become a real editor, and the agent is available on every page.

**Spec:** `docs/superpowers/specs/2026-03-27-workspace-redesign.md`

---

## G-W1: Sidebar Workspace Tabs + Contextual Content

**Modify:** `dashboard/src/layouts/AppLayout.tsx`

### What to Build

Add three small icon tabs below the agent name in the sidebar header. These switch both the sidebar content AND navigate to the workspace:

```tsx
// Below the agent name button
<div className="flex items-center gap-1 px-3 pb-2">
  <button
    onClick={() => navigate('/')}
    className={`flex-1 p-2 rounded-md flex items-center justify-center ${isChat ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:bg-muted'}`}
    title="Chat"
  >
    <MessageCircle className="h-4 w-4" />
  </button>
  <button
    onClick={() => navigate('/notebooks')}
    className={`flex-1 p-2 rounded-md flex items-center justify-center ${isNotebook ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:bg-muted'}`}
    title="Notebooks"
  >
    <FileText className="h-4 w-4" />
  </button>
  <button
    onClick={() => navigate('/kanban')}
    className={`flex-1 p-2 rounded-md flex items-center justify-center ${isKanban ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:bg-muted'}`}
    title="Boards"
  >
    <Columns3 className="h-4 w-4" />
  </button>
</div>
```

Route detection:
```typescript
const isChat = location.pathname === '/' || searchParams.has('c')
const isNotebook = location.pathname.startsWith('/notebooks')
const isKanban = location.pathname.startsWith('/kanban')
const isSettings = location.pathname.startsWith('/settings')
```

### Sidebar Content Switching

The `ScrollArea` content should change based on the active workspace:

**When `isChat`:** Show conversation list (current behavior, no changes)

**When `isNotebook`:** Show notebook list + entries for active notebook
```tsx
// Fetch notebooks list
const [notebooks, setNotebooks] = useState([])
// In sidebar:
<div className="space-y-1">
  <div className="px-3 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/70 mb-2">Notebooks</div>
  {notebooks.map(nb => (
    <button
      key={nb.id}
      onClick={() => navigate(`/notebooks/${nb.id}`)}
      className={`w-full text-left px-3 py-2 rounded-md text-sm truncate ${activeNotebookId === nb.id ? 'bg-accent text-accent-foreground' : 'text-muted-foreground hover:bg-accent/50'}`}
    >
      {nb.title}
    </button>
  ))}
  <button onClick={createNewNotebook} className="w-full text-left px-3 py-2 rounded-md text-sm text-muted-foreground hover:bg-accent/50">
    <Plus className="h-3 w-3 inline mr-1" /> New notebook
  </button>
</div>
```

**When `isKanban`:** Show board list
```tsx
<div className="space-y-1">
  <div className="px-3 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/70 mb-2">Boards</div>
  {boards.map(b => (
    <button key={b.id} onClick={() => navigate(`/kanban/${b.id}`)} ...>
      {b.title}
    </button>
  ))}
  <button onClick={createNewBoard} ...>
    <Plus /> New board
  </button>
</div>
```

**When `isSettings`:** Settings section list (current behavior, no changes)

### Data Fetching

Notebook and board lists should be fetched when their tab is first activated, then cached. Use state in AppLayout:

```typescript
const [notebooks, setNotebooks] = useState<{id: string, title: string, updated_at: string}[]>([])
const [boards, setBoards] = useState<{id: string, title: string, updated_at: string}[]>([])

useEffect(() => {
  if (isNotebook && notebooks.length === 0) {
    get('/api/notebooks').then(d => setNotebooks(d.notebooks))
  }
  if (isKanban && boards.length === 0) {
    get('/api/kanban/boards').then(d => setBoards(d.boards))
  }
}, [isNotebook, isKanban])
```

### Hide Conversation Search

The conversation search input should only show when `isChat`:
```tsx
{!collapsed && isChat && (
  <div className="px-3 pb-2 pt-1 mb-2">
    <Input placeholder="Search conversations..." ... />
  </div>
)}
```

### Icons to Import
```typescript
import { FileText, Columns3 } from 'lucide-react'
```

### Testing
- [ ] Three tabs visible in sidebar
- [ ] Active tab highlighted based on current route
- [ ] Click Notes tab → navigates to /notebooks, sidebar shows notebook list
- [ ] Click Boards tab → navigates to /kanban, sidebar shows board list
- [ ] Click Chat tab → navigates to /, sidebar shows conversations
- [ ] Sidebar collapses/expands independently of tabs
- [ ] Settings still works (tabs hidden on settings, section list shown)
- [ ] Mobile: tabs visible in mobile sidebar overlay

---

## G-W2: Notebook Editor Rewrite

**Rewrite:** `dashboard/src/pages/NotebookPage.tsx`

### What to Build

Replace the current entry-list + textarea with a continuous markdown editor.

### Layout

```
┌──────────────────────────────────────────────┐
│  [Title: Daily Journal          ]  (editable) │
│  ──────────────────────────────────────────── │
│                                              │
│  ## March 27, 2026                           │  ← auto date separator
│                                              │
│  [Full markdown editor content here]         │
│  The user writes freely. Markdown renders    │
│  in live preview. Content auto-saves.        │
│                                              │
│  ---                                         │  ← separator between entries
│                                              │
│  ## March 26, 2026                           │
│                                              │
│  [Previous entry content]                    │
│                                              │
├──────────────────────────────────────────────┤
│ [Agent Name] type / or click...         🎤 ↑ │  ← agent input (G-W3)
└──────────────────────────────────────────────┘
```

### Editor Component

Reuse the existing `MarkdownEditor` from `dashboard/src/components/Editor.tsx` (already used by ArtifactPreview for editable artifacts). It uses Tiptap which supports:
- Live markdown preview
- Headings, bold, italic, lists, code blocks, links
- Keyboard shortcuts (Cmd+B, Cmd+I, etc.)

### Entry Rendering

Each notebook entry becomes a section in the continuous editor. Entries are separated by a horizontal rule and a date header:

```tsx
function buildDocumentContent(entries: NotebookEntry[]): string {
  // Group entries by date, newest first
  const grouped = groupByDate(entries)
  const sections = []
  for (const [date, dateEntries] of grouped) {
    sections.push(`## ${formatDate(date)}`)
    for (const entry of dateEntries) {
      sections.push(entry.content)
    }
  }
  return sections.join('\n\n---\n\n')
}
```

### Auto-Save

When the editor content changes:
1. Debounce 1.5 seconds
2. Diff the content against the original entries to find what changed
3. PATCH changed entries via `PATCH /api/notebooks/{id}/entries/{entry_id}` with `{ "content": "..." }`

A simpler approach: treat the entire document as the latest entry's content. When the user types at the bottom, create a new entry. When they edit existing text, update that entry.

**Simplest viable approach:** Each entry has its own editor instance stacked vertically, with date headers between them. This avoids the complexity of diffing a single document while still looking like a continuous flow.

```tsx
<div className="space-y-0">
  {entriesByDate.map(([date, entries]) => (
    <div key={date}>
      <div className="text-xs text-muted-foreground font-medium py-4 px-2">{formatDate(date)}</div>
      {entries.map(entry => (
        <EntryEditor
          key={entry.id}
          entry={entry}
          onSave={(content) => debouncedPatch(entry.id, content)}
          onDelete={() => deleteEntry(entry.id)}
        />
      ))}
    </div>
  ))}
  {/* New entry area at bottom */}
  <NewEntryEditor
    onSubmit={(content) => createEntry(content)}
    placeholder="Start writing..."
  />
</div>
```

### EntryEditor Component

```tsx
function EntryEditor({ entry, onSave, onDelete }) {
  const [content, setContent] = useState(entry.content)
  const saveTimeout = useRef(null)

  const handleChange = (newContent: string) => {
    setContent(newContent)
    clearTimeout(saveTimeout.current)
    saveTimeout.current = setTimeout(() => onSave(newContent), 1500)
  }

  return (
    <div className="group relative">
      <MarkdownEditor
        value={content}
        onChange={handleChange}
        placeholder="Write something..."
        className="min-h-[100px] border-none focus:ring-0"
      />
      {/* Delete button on hover */}
      <button
        onClick={onDelete}
        className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive"
      >
        <Trash2 className="h-3 w-3" />
      </button>
    </div>
  )
}
```

### Title

Editable inline at the top:
```tsx
<input
  value={title}
  onChange={(e) => setTitle(e.target.value)}
  onBlur={() => saveTitle(title)}
  className="text-2xl font-bold bg-transparent border-none focus:outline-none w-full"
  placeholder="Untitled notebook"
/>
```

### Remove Old UI Elements

- Remove "general · read" labels
- Remove "Ask Agent" button (replaced by agent input bar in G-W3)
- Remove the old textarea for adding entries (replaced by NewEntryEditor at bottom)
- Remove entry cards with timestamps (entries flow as continuous content)
- Remove `activeMobileTab` ("write"/"history") toggle

### API Endpoints (all exist)
- `GET /api/notebooks/{id}` — returns notebook + entries
- `POST /api/notebooks/{id}/entries` — create new entry
- `PATCH /api/notebooks/{id}/entries/{entry_id}` — update entry content
- `DELETE /api/notebooks/{id}/entries/{entry_id}` — delete entry
- `PATCH /api/notebooks/{id}` — update title

### Testing
- [ ] Notebook loads with entries rendered as continuous content
- [ ] Date headers separate entries by day
- [ ] Editing an entry auto-saves after 1.5s
- [ ] New entry created by typing at bottom
- [ ] Title is editable inline
- [ ] Delete entry on hover
- [ ] No "general · read" labels
- [ ] No "Ask Agent" button
- [ ] Markdown renders in live preview
- [ ] Mobile: full-width editor, scrollable

---

## G-W3: Agent Input Bar

**Create:** `dashboard/src/components/AgentInputBar.tsx`

A shared component rendered at the bottom of notebook and kanban pages.

### Props
```typescript
interface AgentInputBarProps {
  agentName: string
  placeholder?: string        // "Ask about this notebook..."
  pageContext: Record<string, any>  // sent with every message
  socketRef: React.MutableRefObject<ChatSocket | null>
  connected: boolean
  sttAvailable: boolean
  onResponse?: (content: string) => void  // for inline display
}
```

### States

**Collapsed (default):**
```tsx
<div className="flex items-center gap-2 px-4 py-2 text-sm text-muted-foreground cursor-pointer"
     onClick={() => setFocused(true)}>
  <span className="font-medium">{agentName}</span>
  <span className="text-xs">type / or click to ask...</span>
</div>
```

**Focused:**
```tsx
<div className="flex items-center gap-2 px-4 py-2 border-t border-border/20">
  <textarea
    ref={inputRef}
    value={input}
    onChange={e => setInput(e.target.value)}
    onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }}
    onKeyDown={e => { if (e.key === 'Escape') setFocused(false) }}
    placeholder={placeholder}
    className="flex-1 bg-transparent border-none resize-none text-sm focus:outline-none"
    rows={1}
    autoFocus
  />
  {sttAvailable && <Mic className="h-4 w-4 text-muted-foreground cursor-pointer" />}
  <button onClick={send} disabled={!input.trim()}>
    <ArrowUp className="h-4 w-4" />
  </button>
</div>
```

**Hidden (focus mode):**
Not rendered. Controlled by parent component's focus mode state.

### Sending Messages

```typescript
function send() {
  if (!input.trim()) return
  socketRef.current?.send('chat', {
    content: input,
    context: pageContext,
  })
  setInput('')
  setWaitingForResponse(true)
}
```

### Keyboard

- `Enter` — send (Shift+Enter for newline)
- `Escape` — unfocus/hide
- `/` from anywhere on the page — focus the input bar

Add a global keydown listener on the page:
```typescript
useEffect(() => {
  const handler = (e: KeyboardEvent) => {
    if (e.key === '/' && !['INPUT', 'TEXTAREA'].includes((e.target as HTMLElement).tagName)) {
      e.preventDefault()
      setFocused(true)
    }
  }
  window.addEventListener('keydown', handler)
  return () => window.removeEventListener('keydown', handler)
}, [])
```

### Testing
- [ ] Shows agent name and hint text when collapsed
- [ ] Click expands to focused input
- [ ] Enter sends message with page context
- [ ] Escape hides/unfocuses
- [ ] / from anywhere focuses the bar
- [ ] Mic button visible when STT available
- [ ] Works on notebook page
- [ ] Works on kanban page

---

## G-W4: Inline Response Popover

**Modify:** `dashboard/src/components/AgentInputBar.tsx`

When the agent responds to a workspace query, show the response as a floating popover above the input bar — don't navigate to chat.

```tsx
{response && (
  <div className="absolute bottom-full left-0 right-0 mx-4 mb-2 max-h-[300px] overflow-y-auto rounded-xl border border-border/40 bg-background p-4 shadow-lg animate-in slide-in-from-bottom-2">
    <div className="prose prose-sm dark:prose-invert max-w-none">
      <Markdown>{response}</Markdown>
    </div>
    <div className="flex justify-end mt-2 gap-2">
      <button onClick={() => setResponse(null)} className="text-xs text-muted-foreground hover:text-foreground">
        Dismiss
      </button>
      <button onClick={() => { navigate('/'); /* pass conversation context */ }} className="text-xs text-primary hover:text-primary/80">
        Continue in chat
      </button>
    </div>
  </div>
)}
```

The `AgentInputBar` needs to listen for WebSocket `chat_response` messages. Use the existing `onMessage` handler from the socket or pass responses down via outlet context.

### Testing
- [ ] Agent response shows as popover above input bar
- [ ] Popover has max height with scroll
- [ ] "Dismiss" closes the popover
- [ ] "Continue in chat" navigates to chat page
- [ ] Popover doesn't block the editor
- [ ] Multiple responses replace the previous popover

---

## G-W5: Focus Mode

**Modify:** `dashboard/src/pages/NotebookPage.tsx`, `dashboard/src/pages/KanbanPage.tsx`

### Toggle
```typescript
const [focusMode, setFocusMode] = useState(false)

// Keyboard shortcut
useEffect(() => {
  const handler = (e: KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key === '.') {
      e.preventDefault()
      setFocusMode(prev => !prev)
    }
    if (e.key === 'Escape' && focusMode) {
      setFocusMode(false)
    }
  }
  window.addEventListener('keydown', handler)
  return () => window.removeEventListener('keydown', handler)
}, [focusMode])
```

### Effect
When `focusMode` is true:
- Hide the agent input bar
- Tell AppLayout to hide the sidebar: pass `focusMode` via outlet context or use a CSS class on the root
- The editor fills the entire viewport

```tsx
// In NotebookPage, wrap the editor:
<div className={focusMode ? 'fixed inset-0 z-50 bg-background p-8 overflow-y-auto' : ''}>
  {/* editor content */}
</div>
```

### Edge Reveal
When in focus mode, moving the mouse to the left edge briefly reveals the sidebar:
```tsx
{focusMode && (
  <div
    className="fixed left-0 top-0 bottom-0 w-4 z-[60] hover:w-64 transition-all group"
    onMouseEnter={() => setEdgeHover(true)}
    onMouseLeave={() => setEdgeHover(false)}
  >
    {edgeHover && <Sidebar />}
  </div>
)}
```

Or simpler: just use `Escape` to exit and `Cmd+.` to enter. No edge reveal needed.

### Testing
- [ ] Cmd+. toggles focus mode
- [ ] Editor fills entire screen in focus mode
- [ ] Sidebar and agent input hidden
- [ ] Escape exits focus mode
- [ ] Works on both notebook and kanban

---

## G-W6: Kanban Sidebar + Agent Input

**Modify:** `dashboard/src/pages/KanbanPage.tsx`

### Changes
1. Remove the board list header from the kanban main area (it moves to the sidebar via G-W1)
2. Add `AgentInputBar` at the bottom of the kanban page
3. Board title editable inline (same pattern as notebook)
4. Focus mode support (Cmd+.)

### Agent Input on Kanban
```tsx
<AgentInputBar
  agentName={agentName}
  placeholder="Ask about this board..."
  pageContext={{
    page: 'kanban',
    page_id: boardId,
    page_title: board.title,
    visible_data: `Columns: ${columns.map(c => c.title).join(', ')}. ${cards.length} cards.`
  }}
  socketRef={socketRef}
  connected={connected}
  sttAvailable={sttAvailable}
/>
```

### Testing
- [ ] Board list in sidebar (from G-W1)
- [ ] Agent input bar at bottom of board
- [ ] Board title editable
- [ ] Focus mode works

---

## G-W7: Remove Quick Links + Clean Navigation

**Modify:** `dashboard/src/components/ChatPanel.tsx`

Remove the quick links row at the bottom of the chat input:
```
Journal · Board · Documents · Voice · Email
```

These are replaced by the workspace tabs in the sidebar (G-W1). Keep only "Voice" if STT is available (since voice mode is an input method, not navigation).

Actually, remove ALL of them. Voice is accessible via the mic button. Navigation is in the sidebar tabs.

### Also Remove
- Any remaining references to the old notebook "general · read" labels
- The "Ask Agent" button from notebook
- Old `voiceMode` state/VoiceOrb in ChatPanel if not being used in the new flow

### Testing
- [ ] No quick links below chat input
- [ ] Chat input is clean: textarea + mic + send
- [ ] All navigation via sidebar tabs

---

## G-W8: Mobile Adaptations

### Sidebar Tabs on Mobile
The workspace tabs should be visible in the mobile sidebar overlay. Same three icons.

### Notebook Editor on Mobile
- Full-width editor
- Title at top, entries below
- Agent input bar at bottom (fixed position above keyboard)
- Focus mode: just hides the mobile header bar

### Kanban on Mobile
Already has column switcher from previous mobile work. Just add agent input bar.

### Testing
- [ ] Workspace tabs in mobile sidebar
- [ ] Notebook editor full-width on mobile
- [ ] Agent input doesn't get hidden by keyboard
- [ ] Kanban board works with agent input

---

## API Endpoints (all already exist)

### Notebooks
```
GET  /api/notebooks                          → {notebooks: [...]}
POST /api/notebooks                          → creates notebook
GET  /api/notebooks/{id}                     → notebook + entries
PATCH /api/notebooks/{id}                    → update title
DELETE /api/notebooks/{id}                   → delete notebook
POST /api/notebooks/{id}/entries             → create entry
PATCH /api/notebooks/{id}/entries/{eid}      → update entry content
DELETE /api/notebooks/{id}/entries/{eid}     → delete entry
POST /api/notebooks/{id}/share              → generate share link
DELETE /api/notebooks/{id}/share            → revoke share link
```

### Kanban
```
GET  /api/kanban/boards                      → {boards: [...]}
POST /api/kanban/boards                      → create board
GET  /api/kanban/boards/{id}                 → board + columns + cards
PATCH /api/kanban/boards/{id}                → update title
DELETE /api/kanban/boards/{id}               → delete board
POST /api/kanban/boards/{id}/columns         → create column
POST /api/kanban/boards/{id}/cards           → create card
PATCH /api/kanban/cards/{id}                 → update card
DELETE /api/kanban/cards/{id}                → delete card
POST /api/kanban/boards/{id}/share          → share link
```

### WebSocket Chat (for agent input bar)
Same `/api/ws` WebSocket. Send:
```json
{"type": "chat", "content": "...", "context": {"page": "notebook", "page_id": "...", ...}}
```

Receive `chat_response` with optional `actions` array.

---

## Files to Create
- `dashboard/src/components/AgentInputBar.tsx`

## Files to Modify
- `dashboard/src/layouts/AppLayout.tsx` — workspace tabs, sidebar content switching
- `dashboard/src/pages/NotebookPage.tsx` — complete rewrite to editor
- `dashboard/src/pages/KanbanPage.tsx` — sidebar integration, agent input
- `dashboard/src/components/ChatPanel.tsx` — remove quick links
- `dashboard/src/App.tsx` — no route changes needed

## Files to Reference (don't modify)
- `dashboard/src/components/Editor.tsx` — MarkdownEditor and CodeEditor components
- `dashboard/src/components/ArtifactPreview.tsx` — example of MarkdownEditor usage

## Implementation Order
1. G-W1 first (navigation — everything else depends on it)
2. G-W7 (clean up old navigation)
3. G-W2 (notebook editor — biggest task)
4. G-W3 + G-W4 (agent input + response popover)
5. G-W6 (kanban follows notebook pattern)
6. G-W5 (focus mode — polish)
7. G-W8 (mobile — last)
