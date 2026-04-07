# Activity Indicators System (Backlog)

**Date:** 2026-04-07
**Status:** Backlog
**Priority:** After skill & tool system review

## Problem

Background tasks (song generation, image generation, research) run in conversations but the user loses all visibility when they switch to a different conversation. The current background task indicator only shows in the active chat's input area.

## Requirements

### 1. Sidebar activity indicators
- Conversations with active background tasks show a visual indicator (pulse dot, spinner)
- When task completes, indicator changes to completion badge
- Badge persists until user views that conversation
- Unread message count or "new activity" dot for conversations with new system messages

### 2. Cross-conversation notifications
- Background task completion triggers toast notification regardless of which conversation is active
- Toast includes conversation name and result summary
- Clicking toast navigates to that conversation

### 3. Agent awareness across conversations
- Query planner checks for active tasks in OTHER conversations
- Agent can mention: "You have a song generating in your Province Life conversation"
- System prompt includes brief active task summary when relevant

### 4. Unified animation system
- Consistent visual language: pulse for active, check for complete, fade for stale
- Replace piecemeal coverage with a single animation/indicator component
- Apply to: sidebar conversations, background tasks, thinking state, streaming state

## Technical Notes

- uiStore.backgroundTasks already tracks tasks but isn't scoped to conversations
- Need: `backgroundTasksByConversation: Record<string, BackgroundTask[]>`
- Sidebar reads this state and shows per-conversation indicators
- WebSocket `task_completed` already fires — needs to update the right conversation's state
- Agent context: query planner can check `tasks` table for pending/active entries
