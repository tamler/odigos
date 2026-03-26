# Gemini Floating Assistant Bubble Handoff

## Overview

A persistent floating chat bubble that follows the user across all pages. Same agent, same conversation as the main chat — just in a compact, always-available form. The agent automatically knows what page the user is on.

**Spec:** `docs/superpowers/specs/2026-03-26-floating-assistant-design.md`

## Backend APIs (already implemented)

### GET /api/settings
Returns (among other fields):
```json
{
  "assistant": {
    "enabled": true,
    "show_transcript": true,
    "text_input": true,
    "voice_input": true,
    "auto_read": false,
    "position": "bottom-right"
  }
}
```

### POST /api/settings
Body: `{ "assistant": { "enabled": false, ... } }`

### WebSocket /api/ws — Enhanced Response
Chat responses may now include an `actions` array:
```json
{
  "type": "chat_response",
  "content": "Done, I've created the notebook.",
  "actions": [
    {"action": "navigate", "to": "/notebooks/abc123"},
    {"action": "refresh"}
  ],
  "conversation_id": "..."
}
```

### WebSocket Chat Message — Page Context
When sending messages from the bubble, include page context:
```json
{
  "type": "chat",
  "content": "what's on this board?",
  "context": {
    "page": "kanban",
    "page_id": "board-abc",
    "page_title": "Project Alpha",
    "visible_data": "Columns: To Do (3), In Progress (2), Done (5)"
  }
}
```

The `context` field already exists on chat messages (used by cowork mode). Just send richer data.

---

## Tasks

### G-B1: FloatingBubble Component

**Create:** `dashboard/src/components/FloatingBubble.tsx`

A floating chat interface rendered globally in AppLayout.

**Collapsed state:**
- Small circle (48px), positioned per settings (bottom-right or bottom-left), 16px from edges
- Shows a subtle chat/waveform icon
- Draggable (save position to localStorage key `odigos-bubble-pos`)
- Badge count for unread responses (messages received while collapsed)
- Subtle pulse animation when agent sends a response while collapsed

**Expanded state:**
- Rounded panel, 320px wide (mobile: full width - 32px), max 400px tall
- Appears above the bubble button
- Follows app theme (dark/light)
- Header: agent name (from settings `agent.name`), minimize button (X or ChevronDown)
- Body: message transcript (scrollable, shows recent messages from the shared conversation)
- Footer: text input + mic button + send button (each conditionally shown based on settings)
- Click outside to collapse

**Visibility rules:**
- Hidden when `assistant.enabled` is false
- Hidden on chat page (`/` and `/?c=...`) — chat page IS the full interface
- Hidden when chat side panel is open (cowork mode)
- Visible on all other pages (kanban, notebooks, settings, artifacts, etc.)

**Props/State:**
```typescript
interface FloatingBubbleProps {
  socketRef: React.MutableRefObject<ChatSocket | null>
  connected: boolean
  activeConversationId: string | null
  messages: ChatMessage[]  // shared with chat page
  onSend: (content: string, context?: Record<string, any>) => void
  pageContext: PageContext
  assistantConfig: AssistantConfig
  agentName: string
  ttsAvailable: boolean
  sttAvailable: boolean
  playTTS: (text: string) => void
}
```

**Animations:**
- Expand: scale from bubble origin, 200ms ease-out
- Collapse: reverse, 150ms ease-in
- New message: slide in from bottom of transcript

### G-B2: usePageContext Hook

**Create:** `dashboard/src/hooks/usePageContext.ts`

Collects context about the current page for sending with bubble messages.

```typescript
interface PageContext {
  page: string
  page_id?: string
  page_title?: string
  visible_data?: string
}

export function usePageContext(): PageContext
```

Uses `useLocation()` to determine the current page. Each page provides additional context via a shared React context or outlet context.

**Default context (from URL alone):**
```typescript
const path = location.pathname
if (path.startsWith('/kanban')) return { page: 'kanban' }
if (path.startsWith('/notebooks')) return { page: 'notebook' }
if (path.startsWith('/settings')) return { page: 'settings', page_id: tab }
if (path.startsWith('/artifacts')) return { page: 'artifacts' }
// etc.
return { page: path.split('/')[1] || 'home' }
```

**Rich context (from page components):** Each page sets additional context via a shared context provider (see G-B3).

### G-B3: Page Context Providers

**Modify:** Each page component to provide context data.

Add a `PageContextProvider` in AppLayout that pages can update:

```typescript
// In AppLayout:
const [pageContextData, setPageContextData] = useState<Partial<PageContext>>({})

// Pass via outlet context:
setPageContextData  // pages call this to set their context
```

**KanbanPage:** When a board is loaded:
```typescript
setPageContextData({
  page_id: boardId,
  page_title: board.title,
  visible_data: `Columns: ${columns.map(c => `${c.title} (${cardCounts[c.id]})`).join(', ')}`
})
```

**NotebookPage:** When a notebook is loaded:
```typescript
setPageContextData({
  page_id: notebookId,
  page_title: notebook.title,
  visible_data: `${entries.length} entries. Latest: "${entries[0]?.content.slice(0, 80)}..."`
})
```

**SettingsPage:**
```typescript
setPageContextData({
  page_id: activeTab,
  page_title: `Settings > ${tabLabel}`,
})
```

**ArtifactPreview:**
```typescript
setPageContextData({
  page_id: artifactId,
  page_title: artifact.title,
  visible_data: `Type: ${artifact.type}`
})
```

**Files to modify:**
- `dashboard/src/layouts/AppLayout.tsx` — add PageContextProvider, render FloatingBubble
- `dashboard/src/pages/KanbanPage.tsx` — set page context
- `dashboard/src/pages/NotebookPage.tsx` — set page context
- `dashboard/src/pages/SettingsPage.tsx` — set page context
- `dashboard/src/components/ArtifactPreview.tsx` — set page context

### G-B4: Action Handler

**Create:** `dashboard/src/lib/actions.ts`

Processes `actions` array from WebSocket chat_response messages.

```typescript
import { NavigateFunction } from 'react-router-dom'

interface UIAction {
  action: 'navigate' | 'refresh' | 'open_chat' | 'create' | 'theme'
  to?: string
  type?: string
  value?: string
}

export function executeActions(
  actions: UIAction[],
  navigate: NavigateFunction,
  callbacks: {
    refresh: () => void
    openChat: () => void
    setTheme: (theme: string) => void
  }
): void {
  for (const a of actions) {
    switch (a.action) {
      case 'navigate':
        if (a.to) navigate(a.to)
        break
      case 'refresh':
        callbacks.refresh()
        break
      case 'open_chat':
        callbacks.openChat()
        break
      case 'theme':
        if (a.value) callbacks.setTheme(a.value)
        break
      case 'create':
        // POST to create endpoint then navigate
        break
    }
  }
}
```

**Integration:** In AppLayout's WebSocket message handler, when `msg.type === 'chat_response'` and `msg.actions` exists, call `executeActions()`.

### G-B5: Assistant Settings UI

**Create:** `dashboard/src/pages/settings/AssistantTab.tsx`

A settings section for configuring the floating bubble.

**Layout:**
```
Assistant Bubble
─────────────────────────────────
Bubble enabled          [toggle]
Show transcript         [toggle]
Text input              [toggle]
Voice input             [toggle]
Auto-read responses     [toggle]
Position                [dropdown: bottom-right | bottom-left]
```

Each toggle calls `POST /api/settings` with `{ assistant: { key: value } }`.

**Files to modify:**
- `dashboard/src/pages/SettingsPage.tsx` — add Assistant section to SECTIONS array and render AssistantTab

### G-B6: Chat Page Voice Transformation (Phase B)

When voice mode is active (user toggled it), the chat page transforms:
- Text input area replaced by a centered voice orb
- Orb animates based on state (idle, listening, processing, speaking)
- Transcript scrolls above the orb
- Artifacts panel still works alongside

This is the Phase B voice orb from the earlier voice mode spec (`docs/superpowers/specs/2026-03-26-voice-mode-design.md`, Section 5).

**Create:** `dashboard/src/components/VoiceOrb.tsx`

**Orb states:**
| State | Visual |
|-------|--------|
| Idle / Listening | Subtle breathing pulse |
| User speaking | Amplitude rings |
| Processing (STT) | Spinning ring |
| Agent thinking | Pulsing glow |
| Agent speaking (TTS) | Rhythmic pulse |

**Voice mode toggle:** A button in the chat input area. When clicked:
- Text input slides out, orb slides in (CSS transition, same space)
- MediaRecorder starts
- After user stops speaking (~1.5s silence), audio sent to STT WebSocket
- Transcribed text auto-sends as chat message
- Agent response auto-reads via TTS
- Cycle continues until user exits voice mode

**Exit:** Click orb again, press Escape, or click "exit voice" link.

### G-B7: Mobile Bubble

- Bubble repositions to avoid keyboard
- Expanded state: full width minus 32px margins
- Tap outside to dismiss
- Respects safe area insets (already set up from G-P1)
- Drag constrained to screen bounds
- On very small screens (<360px), expanded bubble is truly full-width

---

## Icons to Import

```typescript
import { MessageCircle, Minimize2, GripHorizontal } from 'lucide-react'
```
(Plus existing: Mic, MicOff, Volume2, ArrowUp, Square, X)

## Files to Create
- `dashboard/src/components/FloatingBubble.tsx`
- `dashboard/src/components/VoiceOrb.tsx`
- `dashboard/src/hooks/usePageContext.ts`
- `dashboard/src/lib/actions.ts`
- `dashboard/src/pages/settings/AssistantTab.tsx`

## Files to Modify
- `dashboard/src/layouts/AppLayout.tsx` — render bubble, page context provider, action handler
- `dashboard/src/pages/KanbanPage.tsx` — set page context
- `dashboard/src/pages/NotebookPage.tsx` — set page context
- `dashboard/src/pages/SettingsPage.tsx` — add Assistant section + tab
- `dashboard/src/components/ArtifactPreview.tsx` — set page context
- `dashboard/src/components/ChatPanel.tsx` — voice orb toggle in input area

## Testing Checklist
- [ ] Bubble appears on kanban, notebook, settings, artifacts pages
- [ ] Bubble hidden on chat page
- [ ] Expand/collapse animation works
- [ ] Sending message from bubble appears in main chat history
- [ ] Page context sent with bubble messages (check WebSocket inspector)
- [ ] Agent response with `actions: [{action: "refresh"}]` triggers page refresh
- [ ] Agent response with `actions: [{action: "navigate", to: "/notebooks/x"}]` navigates
- [ ] Drag bubble to new position, reload page, position preserved
- [ ] All assistant settings toggles work (disable bubble hides it, etc.)
- [ ] Voice orb appears on chat page when voice mode toggled
- [ ] Mobile: bubble responsive, keyboard doesn't cover it
- [ ] Auto-read works from bubble (if enabled)
- [ ] Mic button in bubble starts STT (if voice_input enabled and stt available)
