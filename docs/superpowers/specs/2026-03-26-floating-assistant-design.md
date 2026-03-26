# Floating Assistant Bubble Design

**Date:** 2026-03-26
**Status:** Draft

## Overview

A persistent, floating chat interface that follows the user across all pages. The agent sees what page the user is on, what they're looking at, and can respond with both text and UI actions. Works with voice or text. Fully configurable from off to full mini-chat.

This is not a command palette or a separate channel. It IS the chat — the same agent, same conversation — in a compact, always-available form.

## Core Concept

The user is on a kanban board. They tap the bubble, say "add a card called deploy voice to In Progress." The agent uses its existing kanban tools, the board refreshes, the bubble shows "Done, added to In Progress." The user never left the kanban page.

Or: the user is writing in a notebook. They say "read back what I just wrote." The agent sees the notebook context, reads the latest entry via TTS. The user keeps writing.

Or: the user is in settings. They say "what's my current budget?" The bubble shows the answer. No navigation needed.

## Architecture

### Page Context (the UI tells the agent where the user is)

Every message sent through the bubble includes rich page context. We own the entire UI — we know exactly what the user is looking at.

```typescript
interface PageContext {
  page: string              // "chat" | "kanban" | "notebook" | "settings" | "artifacts" | ...
  page_id?: string          // board_id, notebook_id, conversation_id, etc.
  page_title?: string       // "Project Alpha" board, "Daily Journal" notebook
  selected_items?: string[] // selected card IDs, highlighted text, etc.
  visible_data?: string     // summary of what's on screen (column names, entry preview, etc.)
}
```

Each page component exports a `usePageContext()` hook or provides context via the outlet. The bubble reads this and includes it with every message sent to the agent.

The agent receives this as `context_metadata` — the same mechanism already used for `board_id` and `notebook_id` in the cowork chat. We just make it richer and automatic.

### Agent Response Actions

The agent can include UI actions in its response. These are side effects — the text response shows in the bubble, the action executes in the frontend.

```typescript
interface AgentAction {
  action: "navigate" | "refresh" | "open_chat" | "create" | "theme"
  to?: string           // for navigate: URL path
  type?: string         // for create: "notebook" | "board" | "chat"
  value?: string        // for theme: "dark" | "light"
}
```

Actions are returned as part of the WebSocket response:
```json
{
  "type": "chat_response",
  "content": "Done, moved the card to Done column.",
  "actions": [{"action": "refresh"}],
  "conversation_id": "..."
}
```

The bubble's message handler executes actions automatically after displaying the text.

### Backend: Page Context in System Prompt

The `context_metadata` already flows through to the prompt builder. We extend it:

In `prompt_builder.py`, the `page_context` parameter already exists. We make it richer:

```
The user is currently viewing: {page} — {page_title}
{visible_data}

You can respond with UI actions by including an "actions" array in your response metadata.
Available actions: navigate(path), refresh, open_chat, create(type), theme(dark|light)
```

The executor parses any `actions` from the LLM response and includes them in the WebSocket message.

## Bubble UI

### Configuration

Settings > Assistant section with individual toggles:

| Setting | Default | Description |
|---------|---------|-------------|
| Bubble enabled | on | Show the floating bubble |
| Show transcript | on | Show message history when expanded |
| Text input | on | Show text input field in bubble |
| Voice input | on | Show mic button in bubble |
| Auto-read responses | off | TTS reads responses aloud (shared with chat setting) |
| Position | bottom-right | bottom-right or bottom-left |

All stored server-side in config.yaml under a new `assistant` config section. Simple on/off toggles — no "modes" to explain.

### Chat Page Transformation

When the user navigates to the chat page:
- **If voice mode is not active:** Normal text chat UI. Bubble hides (redundant).
- **If voice mode is active:** Chat page transforms into the voice experience — centered orb, transcript scrolling above, artifacts panel to the side. The text input is replaced by the voice orb (Phase B design). The bubble hides here too.

The chat page is never dead. It's either the text chat or the voice studio.

### Visual Design

**Collapsed state:**
- Small circle (48px), bottom-right corner, 16px from edges
- Agent's avatar or a subtle waveform icon
- Draggable to reposition (position saved in localStorage)
- Subtle pulse when agent has something to say (morning briefing, notification)
- Badge count for unread responses

**Expanded state (compact/full):**
- Rounded panel, 320px wide, max 400px tall
- Appears above the bubble button
- Dark/light follows app theme
- Header: agent name, minimize button, mode toggle
- Body: message transcript (compact: last 2-3, full: scrollable)
- Footer: text input + mic button + send
- Auto-read toggle (inherits from chat setting)
- Click outside to collapse

**Animations:**
- Expand: scale from bubble origin, 200ms ease-out
- Collapse: reverse, 150ms
- New message: slide in from bottom
- Agent speaking: bubble pulses with TTS rhythm

### Mobile

- Bubble repositions to avoid keyboard
- Expanded state is wider (full width - 32px margin)
- Tap outside to dismiss
- Respects safe area insets

## Shared State with Chat Page

**Critical: the bubble and the chat page are the SAME conversation.**

- Both use `socketRef` from AppLayout (already shared)
- Both display from the same `messages` array
- Sending from the bubble is identical to sending from chat — same WebSocket, same `conversation_id`
- The chat page shows the full history; the bubble shows the tail
- If you send from the bubble while on the chat page, the message appears in both
- If you're on another page, messages from the bubble still save to the conversation

### Chat Page Behavior

Bubble hides on the chat page — it's redundant since the chat page IS the full interface. When voice mode is active, the chat page shows the voice orb instead of the text input (Phase B).

## Page Context Collection

Each page provides its context. This happens at the layout level via outlet context:

### KanbanPage
```typescript
{
  page: "kanban",
  page_id: boardId,
  page_title: board.title,
  visible_data: `Columns: ${columns.map(c => c.title).join(', ')}. ${cards.length} cards total.`
}
```

### NotebookPage
```typescript
{
  page: "notebook",
  page_id: notebookId,
  page_title: notebook.title,
  visible_data: `${entries.length} entries. Latest: "${entries[0]?.content.slice(0, 100)}..."`
}
```

### SettingsPage
```typescript
{
  page: "settings",
  page_id: activeTab,
  page_title: `Settings > ${tabLabel}`,
}
```

### ArtifactPreview
```typescript
{
  page: "artifact",
  page_id: artifactId,
  page_title: artifact.title,
  visible_data: `Type: ${artifact.type}. ${artifact.content.length} chars.`
}
```

### Default (any page without specific context)
```typescript
{
  page: location.pathname.split('/')[1] || "home",
}
```

## Implementation Plan

### Backend Changes (minimal)

1. **Extend WebSocket message with page_context** — the `chat` message type already supports a `context` field. We just send richer data from the bubble.

2. **Extend prompt builder page_context** — already exists, just format the richer data into the system prompt.

3. **Action responses from executor** — when the LLM response includes action directives, extract and include in the WebSocket response as an `actions` array. Simple post-processing in `ws.py`.

### Frontend Changes

1. **FloatingBubble component** — new standalone component rendered in AppLayout, outside the main content area. Contains its own mini-chat UI.

2. **usePageContext hook** — collects page context from the current route. Each page provides data via outlet context or a shared context provider.

3. **Action handler** — processes `actions` from WebSocket responses: navigate, refresh, etc.

4. **Bubble settings** — mode selector in Settings > General.

5. **Drag + position persistence** — localStorage for bubble position.

### Files to Create
- `dashboard/src/components/FloatingBubble.tsx` — the bubble component
- `dashboard/src/hooks/usePageContext.ts` — page context collection hook

### Files to Modify
- `dashboard/src/layouts/AppLayout.tsx` — render FloatingBubble, provide page context
- `dashboard/src/pages/KanbanPage.tsx` — export page context
- `dashboard/src/pages/NotebookPage.tsx` — export page context
- `dashboard/src/pages/SettingsPage.tsx` — export page context
- `dashboard/src/components/ArtifactPreview.tsx` — export page context
- `odigos/api/ws.py` — pass richer page context, extract actions from response
- `odigos/core/context.py` — format page context into system prompt

## What This Enables

- Voice-first workflow across the entire app
- "Hey, what's on my board?" from any page
- "Create a new notebook called Meeting Notes" without navigating
- "Turn on dark mode" from anywhere
- Agent-initiated navigation: "I created the artifact, let me show you" → navigates to artifact
- Morning briefing appears as a bubble notification, not just a chat message
- The agent becomes an ambient assistant, not a chat window

## Gemini / Claude Split

### Gemini Tasks (frontend)
1. **FloatingBubble component** — the bubble UI with expand/collapse, transcript, text input, mic, drag, position persistence. Reads config from settings API.
2. **usePageContext hook** — collects context from current route/page. Each page provides data via outlet context.
3. **Page context providers** — update KanbanPage, NotebookPage, SettingsPage, ArtifactPreview to export page context data.
4. **Action handler** — process `actions` array from WebSocket responses (navigate, refresh, create, theme).
5. **Bubble settings UI** — new "Assistant" section in Settings with the toggle controls.
6. **Chat page voice transformation** — when voice mode is active, chat page shows orb instead of text input (Phase B orb).
7. **Mobile bubble** — responsive sizing, keyboard avoidance, safe areas.

### Claude Tasks (backend)
1. **AssistantConfig** — new config section in config.py for bubble settings.
2. **Richer page_context in prompt** — extend prompt_builder to format page context into useful system prompt text.
3. **Action extraction in ws.py** — parse action directives from LLM response, include in WebSocket message.
4. **Settings API** — add assistant config to GET/POST settings endpoints.

## Future Extensions

- Agent-initiated bubble expand (proactive suggestions)
- Bubble shows typing indicator when agent is working on a background task
- Keyboard shortcut to focus bubble (Cmd+J or similar)
- Bubble transcript export
- Multi-agent bubble (switch between agents in the bubble)
