# Conversation & Messaging System Redesign

**Date:** 2026-04-07
**Status:** Draft — needs design session
**Goal:** One consistent, reliable system for all conversation interactions across the entire platform.

## Problems We've Hit

### Data Inconsistency
- `messages.timestamp` vs `peer_messages.created_at` vs `tasks.created_at` — same concept, different names
- Conversation IDs: `web:xxx` prefix sometimes stripped, sometimes not
- Messages exist in 3 places: WebSocket session (recent_turns), Zustand store (UI), SQLite (DB) — no clear source of truth contract

### Conversation Identity
- Conversations bound to channels (`web:`, `telegram:`) — can't continue across channels
- Channel is part of the ID instead of metadata
- Old conversations split into multiples when prefix handling breaks

### Message Injection
- Background task results (songs, images) don't reliably appear in the conversation
- System messages written to DB but not pushed to live UI
- Background indicator gets stuck when callback processing fails
- No way for the agent to proactively inject information into a conversation
- No way for background processes to add contextual updates

### Missing Lifecycle
- No defined contract for: message created → stored → delivered → displayed
- Streaming and final messages have different paths
- Multi-turn tool calling concatenates or splits unpredictably
- No way to know if a message was delivered to the UI

### Proactive Agent Behavior
- Agent will eventually initiate conversations (reminders, insights, task completions)
- Need a "general" area vs specific conversations — focus areas vs global updates
- Agent should be able to inject results without polluting unrelated conversations

## What the System Needs

### 1. Consistent Schema
Every table, every column, same convention:
- `id` TEXT PRIMARY KEY
- `created_at` TEXT DEFAULT (datetime('now')) — ONE name everywhere
- `updated_at` TEXT — when needed
- Foreign keys named consistently: `conversation_id`, `user_id`, etc.

### 2. Single Message Bus
One way to add content to a conversation, used by everything:
- User typing in the chat
- Agent responding
- Background task completing
- Heartbeat injecting proactive updates
- System notifications

The bus writes to DB AND pushes to connected WebSocket clients. No separate paths.

### 3. Conversation Identity
- `id` is a UUID — no channel prefix
- `channel` is a field on the conversation record
- `source_channel` on each message tracks where it came from
- Same conversation accessible from any channel
- "Continue conversation" loads context from any prior channel

### 4. Reliable Delivery
- Message written to DB = source of truth
- WebSocket push = real-time notification (best effort)
- UI reads from DB on load, subscribes to WebSocket for live updates
- If WebSocket misses a message, next DB read catches it
- No message lost, ever

### 5. Activity & Notification System
- Every conversation tracks: active tasks, unread messages, last activity
- Sidebar shows indicators per conversation
- Cross-conversation notifications via toast + badge
- Agent can publish to a conversation from any context (heartbeat, callback, peer message)

### 6. Focus Areas
- Conversations can be pinned/categorized (work, personal, research)
- A "general" or "inbox" area for proactive agent updates that aren't tied to a specific conversation
- Agent decides: does this update belong in an existing conversation or the general area?

## Scope

This touches:
- `schema.sql` — column naming consistency
- `odigos/api/ws.py` — message bus integration
- `odigos/api/callbacks.py` — uses the message bus
- `odigos/core/heartbeat/background.py` — uses the message bus
- `odigos/core/agent.py` — message storage
- `odigos/core/context.py` — message loading
- `dashboard/src/stores/chatStore.ts` — message state
- `dashboard/src/stores/conversationStore.ts` — conversation list + activity
- `dashboard/src/layouts/hooks/useWebSocketHandler.ts` — message delivery
- `dashboard/src/components/chat/MessageDisplay.tsx` — rendering
- `dashboard/src/layouts/AppSidebar.tsx` — activity indicators

## Related Backlog Items (Merged Into This)
- Cross-channel conversations
- Activity indicators system
- Artifacts UI (messages and artifacts should be unified in the conversation flow)
- Background task result delivery
- Proactive agent notifications
- Schema consistency audit
