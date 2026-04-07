# Cross-Channel Conversations (Backlog)

**Date:** 2026-04-07
**Status:** Backlog — needs design session
**Priority:** After current conversation system is stable

## The Insight

Conversations are relationships, not transport bindings. If you're having a heartfelt conversation about something important, you should be able to pick it up regardless of channel. You can call someone and then meet them in person — you don't restart the conversation.

## Current State

- Conversations are channel-bound: `web:xxx`, `telegram:yyy`
- Agent shares memory (profile, facts, experiences) across all conversations
- But conversations themselves don't cross channels
- No way to continue a web conversation on Telegram or vice versa

## What We Need

### Continue Conversation
- A command or mechanism to pick up an existing conversation from any channel
- Load the previous conversation's context (or a summary) into the current channel
- Append to the existing flow
- The conversation ID becomes channel-agnostic — the channel is metadata, not identity

### Design Questions
- Should the conversation ID drop the channel prefix entirely? Just a UUID?
- Should the channel be a property on the conversation record, not part of the ID?
- How does the agent load context from a conversation that started elsewhere?
- What about real-time: if you have web open AND Telegram, do messages sync live?
- What about channel-specific features (web has file upload, Telegram has inline keyboards)?
- Should there be a "conversations" view that shows ALL conversations regardless of channel?

### Architecture Implications
- `channel` becomes a field on the `conversations` table, not part of the ID
- Messages track which channel they came from (for display purposes)
- The agent doesn't care — it sees messages in order regardless of channel
- WebSocket and Telegram handlers both write to the same conversation
- The sidebar shows conversations with channel indicators (web icon, Telegram icon)
- "Continue conversation" on Telegram: `/continue [topic or ID]` → loads context

### Not Needed Now
- This is a Phase 6+ feature
- Current focus: make single-channel conversations work perfectly first
- The conversation system fixes we're doing now lay the foundation
