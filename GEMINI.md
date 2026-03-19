# Odigos -- Gemini Agent Instructions

## Project

Self-hosted AI agent platform. Python/FastAPI backend, React/TypeScript dashboard, SQLite database.

## Your Role

Frontend engineer. You own the dashboard UI at `dashboard/`. Claude handles backend, integration, and code review.

## Current Assignment

Read `docs/GEMINI-HANDOFF.md` for your full task list, architecture reference, and API documentation. Start with tasks G1-G3 (bug fixes), then G4 (mobile polish), then G5 (cowork layout).

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

## Key Files

| File | What |
|---|---|
| `docs/GEMINI-HANDOFF.md` | Your task list and full reference |
| `dashboard/src/App.tsx` | Routes |
| `dashboard/src/layouts/AppLayout.tsx` | Layout, sidebar, WebSocket, navigation |
| `dashboard/src/pages/ChatPage.tsx` | Main chat interface |
| `dashboard/src/lib/api.ts` | HTTP helpers |
| `dashboard/src/lib/ws.ts` | WebSocket client |
| `dashboard/src/components/ui/` | All UI components |

## Tech Stack

React 19, TypeScript, Vite, Tailwind CSS v4, shadcn/ui, react-router-dom v7, Recharts, lucide-react, Sonner
