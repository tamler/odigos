# Notification UI — Activity Page + Notification Bar

**Date:** 2026-04-08
**Status:** Approved
**Goal:** MVP frontend for the notification system and proactive agent output. Two surfaces: an ephemeral notification bar in chat and an Activity page as the agent's command center. Implicit feedback model — no explicit reaction buttons.

## Context

The proactive agent (Phase 8d) writes findings, the notification system persists them, and the API serves them. But there's no frontend to see, interact with, or control any of it. The user can only see proactive output via push notifications and raw brain files. This spec adds the minimum UI to make the proactive agent usable and testable.

## Design

### 1. Notification Bar (Top of Chat)

A bar that appears at the top of the chat area when unread notifications exist. Disappears when there are none.

**Collapsed state:**
- Bell icon with unread count badge
- Latest notification title as preview text
- Auto-fades after 8 seconds if not clicked
- Subtle gradient background, not blocking chat

**Expanded state (click to open):**
- Dropdown below the bar showing recent notifications (limit 5)
- Each item: type badge (FINDING / COMPLETED / BRIEFING), title, body preview, timestamp
- Actions per item: "Discuss" (navigate to conversation) and "View artifact" (open brain file in new tab)
- "View all" link navigates to `/activity`
- Close button to collapse

**WebSocket integration:**
- Listen for `notification` events from the bus (already sent by Notifier)
- When a new notification arrives: show the bar, update count
- When all are read: hide the bar

**State:** Add `notifications` and `unreadCount` to a new `useNotificationStore` Zustand store. Fetch on app load via `GET /api/notifications?unread_only=true&limit=5`.

### 2. Activity Page (`/activity`)

A new page accessible from the sidebar navigation. Shows all agent activity time-grouped.

**Layout:**
- Page title: "Activity" with subtitle "What {agent_name} has been up to"
- Filter pills: All | Findings | Status (filter by notification `type`)
- Time groups: Today / Yesterday / Older
- Each notification card: type badge with color, title, body preview, timestamp, action links

**Notification types and their rendering:**

| Type | Badge Color | Icon | Actions |
|------|------------|------|---------|
| `finding` | Purple | magnifying glass | Discuss, View artifact |
| `suggestion` | Blue | lightbulb | Discuss |
| `status` | Green | checkmark | View artifact (if has artifact_path) |
| `alert` | Yellow | warning | Discuss |

**Actions:**
- "Discuss" — if notification has `conversation_id`, navigate to `/?c={id}`. If not, create new conversation via `POST /api/conversations` then navigate. The agent gets artifact context through normal context assembly (the notification's `artifact_path` links to a brain file the agent can read).
- "View artifact" — open `artifact_path` content. For MVP: fetch and display in a modal or new tab. Future: open in the editor.

**Implicit feedback tracking:**
- When a notification card is viewed (scrolled into viewport or page loaded): mark as read via `PATCH /api/notifications/{id} {read: true}`
- Track engagement in a simple `notification_events` approach — log opens, discuss clicks, artifact views to the existing `notifications` table (add `opened_at`, `discussed_at` columns)

### 3. Proactive Settings Tab

A new tab in the Settings page: "Proactive"

**Controls:**
- Toggle: "Proactive mode" — on/off. Maps to `proactive.enabled` in config.yaml
- Slider: "Frequency" — Low (1/hr) / Medium (4/hr) / High (8/hr). Maps to `proactive.max_cycles_per_hour`
- Read-only status: last proactive cycle time, total findings this week, total notifications

**API:** `PATCH /api/settings/proactive` with `{enabled: bool, max_cycles_per_hour: int}`. Backend updates config.yaml and the live heartbeat config.

### 4. Sidebar Navigation Entry

Add "Activity" to the sidebar navigation with a notification badge.

- Icon: bell or activity icon (lucide-react)
- Badge: unread notification count (hidden when 0)
- Position: near the top, after Chat / before Notebooks

### 5. Telegram Support

Telegram channel adapter renders notifications as text messages:
- Finding: "🔍 **{title}**\n{body}\n\nReply /discuss {id} to chat about this"
- Status: "✅ **{title}**\n{body}"
- Briefing: "📋 **{title}**\n{body}"

Slash commands:
- `/activity` — list recent notifications
- `/discuss {id}` — start a conversation about a notification

## File Changes

### Frontend

| File | Change |
|------|--------|
| `dashboard/src/stores/notificationStore.ts` | **New** — Zustand store for notifications + unread count |
| `dashboard/src/components/NotificationBar.tsx` | **New** — ephemeral bar + expandable dropdown |
| `dashboard/src/pages/ActivityPage.tsx` | **New** — full activity feed with filters and time groups |
| `dashboard/src/pages/settings/ProactiveTab.tsx` | **New** — toggle + slider for proactive settings |
| `dashboard/src/layouts/AppSidebar.tsx` | Add Activity nav item with badge |
| `dashboard/src/layouts/AppLayout.tsx` | Mount NotificationBar in chat layout |
| `dashboard/src/layouts/hooks/useWebSocketHandler.ts` | Handle notification events, update store |
| `dashboard/src/App.tsx` or router config | Add /activity route |

### Backend

| File | Change |
|------|--------|
| `schema.sql` | Add opened_at, discussed_at to notifications table |
| `odigos/api/notifications.py` | Add settings endpoint, discuss endpoint |
| `odigos/api/conversations.py` | Support creating conversation with artifact context |

## What Doesn't Change

- Notification persistence (already built in Phase 8d)
- Proactive engine pipeline
- BrainWriter, brain maintenance
- Chat, streaming, message bus
- Existing sidebar conversation list

## Future (Activity Page V2 — separate spec)

- "Working now" live status section
- Goal progress tracking cards
- Calendar prep section
- Budget/usage meters
- Drag-and-drop notification management
- Brain file browser integrated into activity
