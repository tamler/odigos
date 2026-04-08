import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bell } from 'lucide-react'
import { useNotificationStore, type Notification } from '@/stores/notificationStore'

export function NotificationBar() {
  const { notifications, unreadCount, fetchNotifications, fetchUnreadCount, markAsRead, discuss } = useNotificationStore()
  const navigate = useNavigate()
  const [expanded, setExpanded] = useState(false)
  const [visible, setVisible] = useState(false)
  const fadeTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const lastCount = useRef(0)

  useEffect(() => {
    fetchUnreadCount()
    const onVisChange = () => { if (!document.hidden) fetchUnreadCount() }
    document.addEventListener('visibilitychange', onVisChange)
    return () => document.removeEventListener('visibilitychange', onVisChange)
  }, [fetchUnreadCount])

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

  useEffect(() => {
    if (expanded) fetchNotifications(true, 5)
  }, [expanded, fetchNotifications])

  if (unreadCount === 0 && !visible) return null

  const latestUnread = notifications.find((n) => !n.read)

  const handleDiscuss = async (notif: Notification) => {
    const convId = await discuss(notif.id)
    if (convId) navigate(`/?c=${convId}`)
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
      <div
        className={`flex items-center justify-between px-4 py-2 bg-gradient-to-r from-purple-950/50 to-transparent border-b border-purple-500/20 cursor-pointer transition-opacity duration-500 ${visible || expanded ? 'opacity-100' : 'opacity-0 pointer-events-none'}`}
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
            <div key={notif.id} className="px-4 py-3 border-b border-border/50 hover:bg-muted/30 transition-colors">
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
