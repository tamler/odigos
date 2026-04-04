# Odigos -- Gemini Agent Instructions

## Project

Self-hosted AI agent platform. Python/FastAPI backend, React/TypeScript dashboard, SQLite database.

## Your Role

Frontend engineer. You own the dashboard UI at `dashboard/`. Claude handles backend, integration, and code review.

## Current Assignment

Check for handoff docs in this order:
1. `GEMINI-BACKGROUND-TASKS-HANDOFF.md` (background task UI)
2. `GEMINI-SERVICES-HANDOFF.md` (services config)
3. `GEMINI-POLISH-HANDOFF.md` (polish tasks)
4. `docs/GEMINI-HANDOFF.md` (main task list)

## How We Work

1. Read the handoff doc before starting any work
2. Leave notes in the "Communication Log" section at the bottom of the handoff doc when you complete tasks or hit blockers
3. Commit your work with descriptive messages
4. After completing each task, run: `cd dashboard && npx tsc --noEmit && npm run build`

## Rules

- TypeScript must compile with zero errors
- Dashboard must build successfully
- Follow existing patterns in the codebase
- Use shadcn/ui components from `dashboard/src/components/ui/`
- Use `get/post/patch/del` from `@/lib/api` for HTTP calls
- Use `lucide-react` for icons
- Use `sonner` toast for notifications
- No hardcoded colors -- use CSS variables (`hsl(var(--primary))`)
- Primary responsive breakpoint is `lg` (1024px)
- API responses are flat objects (not nested under a key)

## Frontend Architecture (Recently Refactored)

The frontend was decomposed for maintainability. Know this structure:

### Layouts (AppLayout decomposed)
```
dashboard/src/layouts/
├── AppLayout.tsx              -- Layout shell (~200 lines), hook calls + render
├── AppSidebar.tsx             -- Navigation sidebar (memoized)
└── hooks/
    ├── useWebSocketHandler.ts -- WebSocket connection + all message routing
    ├── useConversationActions.ts -- CRUD handlers (new, select, rename, delete, export)
    ├── useRouteState.ts       -- Route detection flags (isSettings, isNotebook, etc.)
    └── useKeyboardShortcuts.ts -- Cmd+K, Cmd+N, Escape
```

### Chat Components (ChatPanel decomposed)
```
dashboard/src/components/
├── ChatPanel.tsx              -- Orchestrator (~400 lines), state + effects + handlers
└── chat/
    ├── MessageDisplay.tsx     -- Message list, streaming, thinking, history
    ├── ChatInputArea.tsx      -- Textarea, file uploads, action buttons, background task indicator
    ├── SuggestedActions.tsx   -- Action chips
    ├── ArtifactGallery.tsx    -- Image/audio artifact cards
    ├── WelcomeView.tsx        -- Empty state with prompts
    └── VoiceModePanel.tsx     -- Voice mode overlay
```

### Zustand Stores
```
dashboard/src/stores/
├── uiStore.ts           -- Sidebar, mobile, focus mode, artifacts, backgroundTasks
├── chatStore.ts         -- Messages, streaming, thinking, status
└── conversationStore.ts -- Conversations, notebooks, boards, images, search
```

### WebSocket Message Types
| Type | Direction | Purpose |
|------|-----------|---------|
| `chat_chunk` | Server→Client | Streaming response token |
| `chat_response` | Server→Client | Complete response with metadata |
| `stream_end` | Server→Client | Streaming finished |
| `task_started` | Server→Client | Background tool initiated |
| `task_completed` | Server→Client | Background tool finished (artifact, result) |
| `title_updated` | Server→Client | Conversation auto-title |
| `notification` | Server→Client | Push notification |
| `status` | Server→Client | Status text (e.g., "Searching...") |
| `queue_update` | Server→Client | Queue depth |

## Key Files

| File | What |
|---|---|
| `docs/GEMINI-HANDOFF.md` | Main task list and full reference |
| `dashboard/src/App.tsx` | Routes |
| `dashboard/src/layouts/AppLayout.tsx` | Layout shell (slim -- logic in hooks/) |
| `dashboard/src/layouts/hooks/useWebSocketHandler.ts` | WebSocket message routing |
| `dashboard/src/components/ChatPanel.tsx` | Chat orchestrator (slim -- UI in chat/) |
| `dashboard/src/components/chat/MessageDisplay.tsx` | Message rendering |
| `dashboard/src/components/chat/ChatInputArea.tsx` | Input area + background task indicator |
| `dashboard/src/stores/uiStore.ts` | Global UI state including backgroundTasks |
| `dashboard/src/lib/api.ts` | HTTP helpers (get/post/patch/del) |
| `dashboard/src/components/ui/` | shadcn/ui components |

## Tech Stack

React 19, TypeScript, Vite, Tailwind CSS v4, shadcn/ui, react-router-dom v7, Zustand, Recharts, lucide-react, Sonner
