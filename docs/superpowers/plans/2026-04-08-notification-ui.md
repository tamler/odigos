# Notification UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** MVP frontend for the notification system — ephemeral notification bar in chat, Activity page as command center, proactive settings tab, sidebar badge. Implicit feedback model.

**Architecture:** A Zustand notification store fetches from `GET /api/notifications` and updates via WebSocket events. The NotificationBar component mounts in the chat layout. The ActivityPage is a new route at `/activity`. The ProactiveTab adds toggle and slider to Settings. All read from the same store and API.

**Tech Stack:** React 19, TypeScript, Zustand, React Router, shadcn/ui, lucide-react, react-markdown, Tailwind CSS 4

---

## File Structure

| File | Responsibility |
|------|---------------|
| `dashboard/src/stores/notificationStore.ts` | **New** — Zustand store: notifications array, unread count, fetch/mark-read actions |
| `dashboard/src/components/NotificationBar.tsx` | **New** — Ephemeral bar + dropdown at top of chat |
| `dashboard/src/pages/ActivityPage.tsx` | **New** — Full activity feed with filters, time groups, infinite scroll |
| `dashboard/src/pages/settings/ProactiveTab.tsx` | **New** — Toggle + slider for proactive settings |
| `dashboard/src/layouts/AppSidebar.tsx` | Add Activity nav button with badge |
| `dashboard/src/layouts/AppLayout.tsx` | Mount NotificationBar |
| `dashboard/src/layouts/hooks/useWebSocketHandler.ts` | Handle notification WS events |
| `dashboard/src/App.tsx` | Add /activity route |
| `schema.sql` | Add opened_at, discussed_at to notifications table |
| `odigos/api/notifications.py` | Add discuss endpoint, settings endpoint |

---

### Task 1: Schema + Backend Additions

Add tracking columns and new API endpoints.

**Files:**
- Modify: `schema.sql`
- Modify: `odigos/api/notifications.py`

- [ ] **Step 1: Add tracking columns to notifications table**

In `schema.sql`, update the notifications table to add:

```sql
    opened_at TEXT,
    discussed_at TEXT,
```

Add these after the `reaction` column, before `created_at`.

- [ ] **Step 2: Add discuss endpoint**

In `odigos/api/notifications.py`, add:

```python
@router.post("/notifications/{notification_id}/discuss")
async def discuss_notification(
    notification_id: str,
    request: Request,
    db: Database = Depends(get_db),
):
    """Start a conversation about a notification. Returns conversation_id."""
    notif = await db.fetch_one(
        "SELECT * FROM notifications WHERE id = ?", (notification_id,)
    )
    if not notif:
        return JSONResponse({"error": "not found"}, status_code=404)

    # Mark as discussed
    await db.execute(
        "UPDATE notifications SET discussed_at = datetime('now'), read = 1 WHERE id = ?",
        (notification_id,),
    )

    # If notification already has a conversation, return it
    if notif["conversation_id"]:
        return {"conversation_id": notif["conversation_id"]}

    # Create new conversation with artifact context
    container = request.app.state.container
    conv_id = await container.message_bus.create_conversation(channel="web")

    # Inject artifact content as first message if available
    artifact_content = ""
    if notif["artifact_path"]:
        from pathlib import Path
        p = Path(notif["artifact_path"])
        if p.exists():
            artifact_content = p.read_text(encoding="utf-8")[:4000]

    if artifact_content:
        await container.message_bus.publish(
            conversation_id=conv_id,
            role="user",
            content=f"Let's discuss your finding: {notif['title']}\n\n{artifact_content}",
            channel="web",
        )

    # Link notification to conversation
    await db.execute(
        "UPDATE notifications SET conversation_id = ? WHERE id = ?",
        (conv_id, notification_id),
    )

    return {"conversation_id": conv_id}
```

Add the required imports at the top: `from fastapi import Request` and `from fastapi.responses import JSONResponse`.

- [ ] **Step 3: Add proactive settings endpoint**

```python
class ProactiveSettingsUpdate(BaseModel):
    enabled: bool | None = None
    max_cycles_per_hour: int | None = None

@router.patch("/settings/proactive")
async def update_proactive_settings(
    update: ProactiveSettingsUpdate,
    request: Request,
    db: Database = Depends(get_db),
):
    """Update proactive engine settings. Takes effect on next heartbeat tick."""
    container = request.app.state.container
    config = getattr(container.heartbeat, '_proactive_config', None)
    if not config:
        return {"error": "proactive config not available"}
    if update.enabled is not None:
        config.enabled = update.enabled
    if update.max_cycles_per_hour is not None:
        config.max_cycles_per_hour = max(1, min(12, update.max_cycles_per_hour))
    return {"status": "ok", "enabled": config.enabled, "max_cycles_per_hour": config.max_cycles_per_hour}

@router.get("/settings/proactive")
async def get_proactive_settings(request: Request):
    """Get current proactive engine settings."""
    container = request.app.state.container
    config = getattr(container.heartbeat, '_proactive_config', None)
    if not config:
        return {"enabled": True, "max_cycles_per_hour": 4}
    return {"enabled": config.enabled, "max_cycles_per_hour": config.max_cycles_per_hour}
```

- [ ] **Step 4: Verify schema**

Run: `sqlite3 :memory: < schema.sql 2>&1 | grep -v vec0`

- [ ] **Step 5: Commit**

```bash
git add schema.sql odigos/api/notifications.py
git commit -m "feat: notification discuss endpoint, proactive settings API, tracking columns"
```

---

### Task 2: Notification Zustand Store

Create the frontend state management for notifications.

**Files:**
- Create: `dashboard/src/stores/notificationStore.ts`

- [ ] **Step 1: Create the store**

```typescript
import { create } from 'zustand'
import { get, patch, post } from '@/lib/api'

export interface Notification {
  id: string
  type: string       // finding, suggestion, status, alert
  title: string
  body: string | null
  artifact_path: string | null
  conversation_id: string | null
  source: string | null
  read: number        // 0 or 1
  created_at: string
  opened_at: string | null
  discussed_at: string | null
}

interface NotificationState {
  notifications: Notification[]
  unreadCount: number
  loading: boolean
  fetchNotifications: (unreadOnly?: boolean, limit?: number, offset?: number) => Promise<Notification[]>
  fetchUnreadCount: () => Promise<void>
  markAsRead: (id: string) => Promise<void>
  addNotification: (notif: Notification) => void
  discuss: (id: string) => Promise<string | null>
}

export const useNotificationStore = create<NotificationState>((set, getState) => ({
  notifications: [],
  unreadCount: 0,
  loading: false,

  fetchNotifications: async (unreadOnly = false, limit = 20, offset = 0) => {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
    if (unreadOnly) params.set('unread_only', 'true')
    try {
      const data = await get<{ notifications: Notification[] }>(`/api/notifications?${params}`)
      const notifs = data.notifications || []
      if (offset === 0) {
        set({ notifications: notifs })
      } else {
        set((s) => ({ notifications: [...s.notifications, ...notifs] }))
      }
      return notifs
    } catch {
      return []
    }
  },

  fetchUnreadCount: async () => {
    try {
      const data = await get<{ notifications: Notification[] }>('/api/notifications?unread_only=true&limit=1')
      // Use a count endpoint if available, otherwise approximate
      const unread = await get<{ notifications: Notification[] }>('/api/notifications?unread_only=true&limit=100')
      set({ unreadCount: (unread.notifications || []).length })
    } catch {
      // ignore
    }
  },

  markAsRead: async (id: string) => {
    try {
      await patch(`/api/notifications/${id}`, { read: true })
      set((s) => ({
        notifications: s.notifications.map((n) => n.id === id ? { ...n, read: 1 } : n),
        unreadCount: Math.max(0, s.unreadCount - 1),
      }))
    } catch {
      // ignore
    }
  },

  addNotification: (notif: Notification) => {
    set((s) => ({
      notifications: [notif, ...s.notifications],
      unreadCount: s.unreadCount + 1,
    }))
  },

  discuss: async (id: string) => {
    try {
      const data = await post<{ conversation_id: string }>(`/api/notifications/${id}/discuss`, {})
      return data.conversation_id || null
    } catch {
      return null
    }
  },
}))
```

- [ ] **Step 2: Verify syntax**

Run: `cd dashboard && npx tsc --noEmit 2>&1 | head -10`

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/stores/notificationStore.ts
git commit -m "feat: notification Zustand store — fetch, mark read, discuss"
```

---

### Task 3: Notification Bar Component

The ephemeral bar + expandable dropdown at the top of chat.

**Files:**
- Create: `dashboard/src/components/NotificationBar.tsx`
- Modify: `dashboard/src/layouts/AppLayout.tsx`

- [ ] **Step 1: Create NotificationBar component**

```typescript
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bell } from 'lucide-react'
import { useNotificationStore, type Notification } from '@/stores/notificationStore'
import { useChatStore } from '@/stores/chatStore'

export function NotificationBar() {
  const { notifications, unreadCount, fetchNotifications, fetchUnreadCount, markAsRead, discuss } = useNotificationStore()
  const navigate = useNavigate()
  const [expanded, setExpanded] = useState(false)
  const [visible, setVisible] = useState(false)
  const fadeTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const lastCount = useRef(0)

  // Fetch unread on mount and on tab focus
  useEffect(() => {
    fetchUnreadCount()
    const onFocus = () => fetchUnreadCount()
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) onFocus()
    })
    return () => document.removeEventListener('visibilitychange', onFocus)
  }, [])

  // Show bar when new notifications arrive
  useEffect(() => {
    if (unreadCount > lastCount.current && unreadCount > 0) {
      setVisible(true)
      if (fadeTimer.current) clearTimeout(fadeTimer.current)
      fadeTimer.current = setTimeout(() => {
        if (!expanded) setVisible(false)
      }, 8000)
    }
    lastCount.current = unreadCount
  }, [unreadCount, expanded])

  // Fetch recent when expanding
  useEffect(() => {
    if (expanded) fetchNotifications(true, 5)
  }, [expanded])

  if (unreadCount === 0 && !visible) return null

  const latestUnread = notifications.find((n) => !n.read)

  const handleDiscuss = async (notif: Notification) => {
    const convId = await discuss(notif.id)
    if (convId) {
      useChatStore.getState().setActiveConversationId(convId)
      navigate(`/?c=${convId}`)
    }
    setExpanded(false)
    setVisible(false)
  }

  const typeColor: Record<string, string> = {
    finding: 'text-purple-400',
    status: 'text-green-400',
    alert: 'text-yellow-400',
    suggestion: 'text-blue-400',
  }

  const typeLabel: Record<string, string> = {
    finding: 'FINDING',
    status: 'COMPLETED',
    alert: 'ALERT',
    suggestion: 'SUGGESTION',
  }

  return (
    <div className="relative">
      {/* Collapsed bar */}
      <div
        className={`flex items-center justify-between px-4 py-2 bg-gradient-to-r from-purple-950/50 to-background border-b border-purple-500/20 cursor-pointer transition-opacity duration-500 ${visible || expanded ? 'opacity-100' : 'opacity-0 pointer-events-none'}`}
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-3">
          <div className="relative">
            <Bell className="h-4 w-4 text-purple-400" />
            {unreadCount > 0 && (
              <span className="absolute -top-1 -right-1.5 w-4 h-4 bg-purple-500 rounded-full text-[9px] text-white flex items-center justify-center font-semibold">
                {unreadCount > 9 ? '9+' : unreadCount}
              </span>
            )}
          </div>
          <span className="text-sm text-purple-200/80 truncate">
            {latestUnread?.title || 'New notifications'}
          </span>
        </div>
        <span className="text-xs text-muted-foreground">{unreadCount} new</span>
      </div>

      {/* Expanded dropdown */}
      {expanded && (
        <div className="absolute top-full left-0 right-0 z-50 bg-card border-b border-border shadow-xl max-h-80 overflow-y-auto">
          <div className="flex items-center justify-between px-4 py-2 border-b border-border">
            <span className="text-sm font-medium">Notifications</span>
            <div className="flex gap-3">
              <button onClick={() => navigate('/activity')} className="text-xs text-muted-foreground hover:text-foreground">View all</button>
              <button onClick={() => { setExpanded(false); setVisible(false) }} className="text-xs text-muted-foreground hover:text-foreground">Close</button>
            </div>
          </div>
          {notifications.filter((n) => !n.read).slice(0, 5).map((notif) => (
            <div
              key={notif.id}
              className="px-4 py-3 border-b border-border/50 hover:bg-muted/30 transition-colors"
            >
              <div className="flex justify-between items-start">
                <div className="flex-1 min-w-0">
                  <span className={`text-[10px] font-semibold tracking-wide ${typeColor[notif.type] || 'text-muted-foreground'}`}>
                    {typeLabel[notif.type] || notif.type.toUpperCase()}
                  </span>
                  <div className="text-xs font-medium mt-0.5 truncate">{notif.title}</div>
                  {notif.body && <div className="text-xs text-muted-foreground mt-1 line-clamp-2">{notif.body}</div>}
                </div>
                <span className="text-[10px] text-muted-foreground ml-3 whitespace-nowrap">
                  {new Date(notif.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </span>
              </div>
              <div className="flex gap-3 mt-2">
                <button onClick={() => handleDiscuss(notif)} className="text-xs text-purple-400 hover:text-purple-300">Discuss</button>
                {notif.artifact_path && (
                  <button onClick={() => markAsRead(notif.id)} className="text-xs text-muted-foreground hover:text-foreground">View artifact</button>
                )}
              </div>
            </div>
          ))}
          {notifications.filter((n) => !n.read).length === 0 && (
            <div className="px-4 py-6 text-center text-xs text-muted-foreground">No unread notifications</div>
          )}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Mount in AppLayout**

In `dashboard/src/layouts/AppLayout.tsx`, import and mount `NotificationBar` at the top of the main content area (above the `<Outlet />`). Find where the main content div starts and add:

```typescript
import { NotificationBar } from '@/components/NotificationBar'
```

And in the JSX, before `<Outlet />`:
```tsx
<NotificationBar />
<Outlet />
```

- [ ] **Step 3: Verify syntax**

Run: `cd dashboard && npx tsc --noEmit 2>&1 | head -10`

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/components/NotificationBar.tsx dashboard/src/layouts/AppLayout.tsx
git commit -m "feat: notification bar — ephemeral bell + expandable dropdown in chat"
```

---

### Task 4: Activity Page

The full notifications page with time-grouped feed and filters.

**Files:**
- Create: `dashboard/src/pages/ActivityPage.tsx`
- Modify: `dashboard/src/App.tsx`

- [ ] **Step 1: Create ActivityPage**

```typescript
import { useEffect, useRef, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useNotificationStore, type Notification } from '@/stores/notificationStore'
import { useChatStore } from '@/stores/chatStore'
import Markdown from 'react-markdown'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'

const TYPE_CONFIG: Record<string, { color: string; label: string; icon: string }> = {
  finding: { color: 'text-purple-400', label: 'FINDING', icon: '🔍' },
  suggestion: { color: 'text-blue-400', label: 'SUGGESTION', icon: '💡' },
  status: { color: 'text-green-400', label: 'COMPLETED', icon: '✅' },
  alert: { color: 'text-yellow-400', label: 'ALERT', icon: '⚠️' },
}

function groupByDate(notifications: Notification[]): Record<string, Notification[]> {
  const groups: Record<string, Notification[]> = {}
  const today = new Date().toDateString()
  const yesterday = new Date(Date.now() - 86400000).toDateString()

  for (const n of notifications) {
    const d = new Date(n.created_at).toDateString()
    const label = d === today ? 'Today' : d === yesterday ? 'Yesterday' : d
    if (!groups[label]) groups[label] = []
    groups[label].push(n)
  }
  return groups
}

export default function ActivityPage() {
  const { notifications, fetchNotifications, markAsRead, discuss } = useNotificationStore()
  const navigate = useNavigate()
  const [filter, setFilter] = useState<string>('all')
  const [offset, setOffset] = useState(0)
  const [hasMore, setHasMore] = useState(true)
  const [artifactContent, setArtifactContent] = useState<string | null>(null)
  const [artifactTitle, setArtifactTitle] = useState('')
  const observerRef = useRef<IntersectionObserver | null>(null)

  useEffect(() => {
    fetchNotifications(false, 20, 0).then((n) => setHasMore(n.length >= 20))
    setOffset(0)
  }, [])

  const loadMore = useCallback(async () => {
    const newOffset = offset + 20
    const n = await fetchNotifications(false, 20, newOffset)
    setOffset(newOffset)
    setHasMore(n.length >= 20)
  }, [offset])

  // Intersection observer for marking read with 500ms delay
  const markReadRef = useCallback((node: HTMLDivElement | null) => {
    if (!node) return
    const id = node.dataset.notifId
    if (!id) return
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            const timer = setTimeout(() => markAsRead(id), 500)
            ;(entry.target as any)._readTimer = timer
          } else {
            clearTimeout((entry.target as any)._readTimer)
          }
        })
      },
      { threshold: 0.5 }
    )
    observer.observe(node)
  }, [markAsRead])

  const handleDiscuss = async (notif: Notification) => {
    const convId = await discuss(notif.id)
    if (convId) {
      useChatStore.getState().setActiveConversationId(convId)
      navigate(`/?c=${convId}`)
    }
  }

  const handleViewArtifact = async (notif: Notification) => {
    if (!notif.artifact_path) return
    try {
      const resp = await fetch(`/api/files/read?path=${encodeURIComponent(notif.artifact_path)}`)
      if (resp.ok) {
        const data = await resp.json()
        setArtifactContent(data.content || 'No content')
        setArtifactTitle(notif.title)
      }
    } catch {
      setArtifactContent('Failed to load artifact')
      setArtifactTitle(notif.title)
    }
    markAsRead(notif.id)
  }

  const filtered = filter === 'all' ? notifications : notifications.filter((n) => n.type === filter)
  const groups = groupByDate(filtered)

  return (
    <div className="max-w-2xl mx-auto px-4 py-6">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h1 className="text-xl font-semibold">Activity</h1>
          <p className="text-sm text-muted-foreground mt-1">What your agent has been up to</p>
        </div>
        <div className="flex gap-1">
          {['all', 'finding', 'status', 'alert'].map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                filter === f ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              {f === 'all' ? 'All' : f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {Object.entries(groups).map(([label, notifs]) => (
        <div key={label} className="mb-6">
          <div className="text-[10px] font-semibold text-muted-foreground tracking-widest mb-2 uppercase">{label}</div>
          {notifs.map((notif) => {
            const config = TYPE_CONFIG[notif.type] || TYPE_CONFIG.status
            return (
              <div
                key={notif.id}
                ref={!notif.read ? markReadRef : undefined}
                data-notif-id={notif.id}
                className={`bg-card rounded-xl p-4 mb-2 border border-border transition-opacity ${notif.read ? 'opacity-60' : ''}`}
              >
                <div className="flex justify-between items-start">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-sm">{config.icon}</span>
                      <span className={`text-[10px] font-semibold tracking-wide ${config.color}`}>{config.label}</span>
                      <span className="text-[10px] text-muted-foreground">
                        {new Date(notif.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                      </span>
                    </div>
                    <div className="text-sm font-medium">{notif.title}</div>
                    {notif.body && <div className="text-xs text-muted-foreground mt-1 line-clamp-3">{notif.body}</div>}
                  </div>
                </div>
                <div className="flex gap-3 mt-3">
                  <button onClick={() => handleDiscuss(notif)} className="text-xs text-primary hover:underline">
                    💬 Discuss
                  </button>
                  {notif.artifact_path && (
                    <button onClick={() => handleViewArtifact(notif)} className="text-xs text-muted-foreground hover:text-foreground">
                      View artifact
                    </button>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      ))}

      {hasMore && (
        <button onClick={loadMore} className="w-full py-3 text-xs text-muted-foreground hover:text-foreground">
          Load more...
        </button>
      )}

      {notifications.length === 0 && (
        <div className="text-center py-12 text-muted-foreground text-sm">
          No activity yet. Your agent will post findings here when it discovers something interesting.
        </div>
      )}

      {/* Artifact viewer modal */}
      <Dialog open={!!artifactContent} onOpenChange={() => setArtifactContent(null)}>
        <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{artifactTitle}</DialogTitle>
          </DialogHeader>
          <div className="prose prose-invert prose-sm max-w-none">
            <Markdown>{artifactContent || ''}</Markdown>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
```

- [ ] **Step 2: Add route in App.tsx**

In `dashboard/src/App.tsx`, add the import and route:

```typescript
const ActivityPage = lazy(() => import('./pages/ActivityPage'))
```

And inside the `<Route element={<AppLayout />}>` block, add:
```tsx
<Route path="/activity" element={<Suspense fallback={null}><ActivityPage /></Suspense>} />
```

- [ ] **Step 3: Verify syntax**

Run: `cd dashboard && npx tsc --noEmit 2>&1 | head -10`

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/pages/ActivityPage.tsx dashboard/src/App.tsx
git commit -m "feat: Activity page — time-grouped feed, filters, discuss, artifact viewer"
```

---

### Task 5: Sidebar Navigation + WebSocket Handler

Add Activity nav item with badge and handle notification WebSocket events.

**Files:**
- Modify: `dashboard/src/layouts/AppSidebar.tsx`
- Modify: `dashboard/src/layouts/hooks/useWebSocketHandler.ts`

- [ ] **Step 1: Add Activity button to sidebar nav**

In `dashboard/src/layouts/AppSidebar.tsx`, find the nav button row (Chat, Notebooks, Boards — around line 173-175). Add an Activity button after Boards:

```tsx
import { Activity } from 'lucide-react'
import { useNotificationStore } from '@/stores/notificationStore'
```

In the component, get unread count:
```tsx
const unreadCount = useNotificationStore((s) => s.unreadCount)
const isActivity = location.pathname === '/activity'
```

Add the button:
```tsx
<button onClick={() => navigate('/activity')} className={`flex-1 p-2 rounded-lg flex items-center justify-center transition-colors relative ${isActivity ? 'bg-primary/10 text-primary shadow-inner' : 'text-muted-foreground hover:bg-muted'}`} title="Activity">
  <Activity className="h-4 w-4" />
  {unreadCount > 0 && (
    <span className="absolute -top-0.5 -right-0.5 w-3.5 h-3.5 bg-purple-500 rounded-full text-[8px] text-white flex items-center justify-center font-bold">
      {unreadCount > 9 ? '!' : unreadCount}
    </span>
  )}
</button>
```

- [ ] **Step 2: Handle notification WebSocket events**

In `dashboard/src/layouts/hooks/useWebSocketHandler.ts`, add a handler for the `notification` event type. The existing handler shows toasts. Add notification store update:

Find the `if (msg.type === 'notification')` block and add after the toast:

```typescript
import { useNotificationStore } from '@/stores/notificationStore'

// Inside the notification handler:
if (msg.type === 'notification') {
  // ... existing toast logic ...

  // Add to notification store if it has an id (persistent notification)
  if (msg.id) {
    useNotificationStore.getState().addNotification({
      id: msg.id as string,
      type: (msg.notification_type as string) || 'status',
      title: (msg.title as string) || '',
      body: (msg.body as string) || null,
      artifact_path: (msg.artifact_path as string) || null,
      conversation_id: (msg.conversation_id as string) || null,
      source: (msg.source as string) || null,
      read: 0,
      created_at: new Date().toISOString(),
      opened_at: null,
      discussed_at: null,
    })
  }
}
```

- [ ] **Step 3: Verify syntax**

Run: `cd dashboard && npx tsc --noEmit 2>&1 | head -10`

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/layouts/AppSidebar.tsx dashboard/src/layouts/hooks/useWebSocketHandler.ts
git commit -m "feat: Activity nav with badge, notification WebSocket handler"
```

---

### Task 6: Proactive Settings Tab

Toggle and slider for proactive engine control.

**Files:**
- Create: `dashboard/src/pages/settings/ProactiveTab.tsx`

- [ ] **Step 1: Create the tab**

```typescript
import { useEffect, useState } from 'react'
import { get, patch } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { toast } from 'sonner'

export default function ProactiveTab() {
  const [enabled, setEnabled] = useState(true)
  const [frequency, setFrequency] = useState(4)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    get<{ enabled: boolean; max_cycles_per_hour: number }>('/api/settings/proactive')
      .then((data) => {
        setEnabled(data.enabled)
        setFrequency(data.max_cycles_per_hour)
      })
      .catch(() => {})
  }, [])

  const save = async () => {
    setSaving(true)
    try {
      await patch('/api/settings/proactive', { enabled, max_cycles_per_hour: frequency })
      toast.success('Proactive settings updated')
    } catch {
      toast.error('Failed to save')
    }
    setSaving(false)
  }

  const freqLabel = frequency <= 1 ? 'Low' : frequency <= 4 ? 'Medium' : 'High'

  return (
    <div className="space-y-6 max-w-md">
      <div>
        <h3 className="text-sm font-medium mb-1">Proactive Mode</h3>
        <p className="text-xs text-muted-foreground mb-3">
          When enabled, your agent proactively researches topics, surfaces insights, and delivers findings to the Activity page.
        </p>
        <label className="flex items-center gap-3 cursor-pointer">
          <div
            className={`w-10 h-6 rounded-full transition-colors relative ${enabled ? 'bg-primary' : 'bg-muted'}`}
            onClick={() => setEnabled(!enabled)}
          >
            <div className={`w-4 h-4 bg-white rounded-full absolute top-1 transition-transform ${enabled ? 'translate-x-5' : 'translate-x-1'}`} />
          </div>
          <span className="text-sm">{enabled ? 'Enabled' : 'Disabled'}</span>
        </label>
      </div>

      {enabled && (
        <div>
          <h3 className="text-sm font-medium mb-1">Frequency</h3>
          <p className="text-xs text-muted-foreground mb-3">
            How often the agent looks for proactive opportunities. Higher = more findings, more token usage.
          </p>
          <div className="flex items-center gap-4">
            <input
              type="range"
              min={1}
              max={8}
              value={frequency}
              onChange={(e) => setFrequency(Number(e.target.value))}
              className="flex-1 accent-primary"
            />
            <span className="text-sm font-medium w-16">{freqLabel} ({frequency}/hr)</span>
          </div>
        </div>
      )}

      <Button onClick={save} disabled={saving} size="sm">
        {saving ? 'Saving...' : 'Save'}
      </Button>
    </div>
  )
}
```

- [ ] **Step 2: Register the tab in SettingsPage**

Find the settings page (likely `dashboard/src/pages/SettingsPage.tsx` or similar). Add a "Proactive" tab that renders `ProactiveTab`. Follow the existing tab pattern — likely a tabs array with `{ id: 'proactive', label: 'Proactive', icon: Activity }` and a lazy-loaded component.

- [ ] **Step 3: Verify syntax**

Run: `cd dashboard && npx tsc --noEmit 2>&1 | head -10`

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/pages/settings/ProactiveTab.tsx
git commit -m "feat: Proactive settings tab — toggle + frequency slider"
```

---

### Task 7: Build + Deploy + Smoke Test

- [ ] **Step 1: Build frontend**

Run: `cd dashboard && npm run build 2>&1 | tail -5`
Expected: Build succeeds

- [ ] **Step 2: Run backend tests**

Run: `python3 -m pytest tests/test_notifications.py tests/test_proactive.py tests/test_brain_writer.py -q 2>&1 | tail -5`
Expected: All pass

- [ ] **Step 3: Push and deploy**

```bash
git push origin main
ssh root@82.25.91.86 "cd /opt/odigos && git fetch origin main && git reset --hard origin/main && chown -R odigos_agent:odigos_agent . && rm -f data/odigos.db* && cd dashboard && npm run build 2>&1 | tail -3 && cd .. && chown -R odigos_agent:odigos_agent . && systemctl restart odigos"
```

- [ ] **Step 4: Verify Activity page loads**

Open browser to `https://jacob.odigos.one/activity`
Expected: Empty state — "No activity yet. Your agent will post findings here."

- [ ] **Step 5: Verify notification bar**

Send a message to create entities. Wait for proactive cycle or manually trigger a notification. The bell should appear at the top of chat.

- [ ] **Step 6: Verify proactive settings**

Navigate to Settings > Proactive. Toggle and slider should load current values. Save should persist.
