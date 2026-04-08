import { create } from 'zustand'
import { get, patch, post } from '@/lib/api'

export interface Notification {
  id: string
  type: string
  title: string
  body: string | null
  artifact_path: string | null
  conversation_id: string | null
  source: string | null
  read: number
  created_at: string
  opened_at: string | null
  discussed_at: string | null
}

interface NotificationState {
  notifications: Notification[]
  unreadCount: number
  fetchNotifications: (unreadOnly?: boolean, limit?: number, offset?: number) => Promise<Notification[]>
  fetchUnreadCount: () => Promise<void>
  markAsRead: (id: string) => Promise<void>
  addNotification: (notif: Notification) => void
  discuss: (id: string) => Promise<string | null>
}

export const useNotificationStore = create<NotificationState>((set) => ({
  notifications: [],
  unreadCount: 0,

  fetchNotifications: async (unreadOnly = false, limit = 20, offset = 0) => {
    const params = new URLSearchParams({ limit: String(limit) })
    if (offset > 0) params.set('offset', String(offset))
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
      const data = await get<{ notifications: Notification[] }>('/api/notifications?unread_only=true&limit=100')
      set({ unreadCount: (data.notifications || []).length })
    } catch {}
  },

  markAsRead: async (id: string) => {
    try {
      await patch(`/api/notifications/${id}`, { read: true })
      set((s) => ({
        notifications: s.notifications.map((n) => n.id === id ? { ...n, read: 1 } : n),
        unreadCount: Math.max(0, s.unreadCount - 1),
      }))
    } catch {}
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
