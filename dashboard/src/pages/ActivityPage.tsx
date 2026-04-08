import { useEffect, useCallback, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useNotificationStore, type Notification } from '@/stores/notificationStore'
import Markdown from 'react-markdown'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'

const TYPE_CONFIG: Record<string, { color: string; label: string; icon: string }> = {
  finding: { color: 'text-purple-400', label: 'FINDING', icon: '~' },
  suggestion: { color: 'text-blue-400', label: 'SUGGESTION', icon: '*' },
  status: { color: 'text-green-400', label: 'COMPLETED', icon: '+' },
  alert: { color: 'text-yellow-400', label: 'ALERT', icon: '!' },
}

function groupByDate(notifications: Notification[]): [string, Notification[]][] {
  const groups: Record<string, Notification[]> = {}
  const today = new Date().toDateString()
  const yesterday = new Date(Date.now() - 86400000).toDateString()

  for (const n of notifications) {
    const d = new Date(n.created_at).toDateString()
    const label = d === today ? 'Today' : d === yesterday ? 'Yesterday' : d
    if (!groups[label]) groups[label] = []
    groups[label].push(n)
  }
  return Object.entries(groups)
}

export default function ActivityPage() {
  const { notifications, fetchNotifications, markAsRead, discuss } = useNotificationStore()
  const navigate = useNavigate()
  const [filter, setFilter] = useState('all')
  const [offset, setOffset] = useState(0)
  const [hasMore, setHasMore] = useState(true)
  const [artifactContent, setArtifactContent] = useState<string | null>(null)
  const [artifactTitle, setArtifactTitle] = useState('')

  useEffect(() => {
    fetchNotifications(false, 20, 0).then((n) => setHasMore(n.length >= 20))
    setOffset(0)
  }, [fetchNotifications])

  const loadMore = useCallback(async () => {
    const newOffset = offset + 20
    const n = await fetchNotifications(false, 20, newOffset)
    setOffset(newOffset)
    setHasMore(n.length >= 20)
  }, [offset, fetchNotifications])

  const handleDiscuss = async (notif: Notification) => {
    const convId = await discuss(notif.id)
    if (convId) navigate(`/?c=${convId}`)
  }

  const handleViewArtifact = async (notif: Notification) => {
    if (!notif.artifact_path) return
    try {
      const resp = await fetch(`/api/files/read?path=${encodeURIComponent(notif.artifact_path)}`)
      if (resp.ok) {
        const data = await resp.json()
        setArtifactContent(data.content || 'No content')
      } else {
        setArtifactContent('Failed to load artifact')
      }
    } catch {
      setArtifactContent('Failed to load artifact')
    }
    setArtifactTitle(notif.title)
    markAsRead(notif.id)
  }

  // Mark as read on scroll with 500ms delay
  const markReadRef = useCallback((node: HTMLDivElement | null) => {
    if (!node) return
    const id = node.dataset.notifId
    if (!id) return
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            const el = entry.target as HTMLDivElement & { _readTimer?: ReturnType<typeof setTimeout> }
            el._readTimer = setTimeout(() => markAsRead(id), 500)
          } else {
            const el = entry.target as HTMLDivElement & { _readTimer?: ReturnType<typeof setTimeout> }
            if (el._readTimer) clearTimeout(el._readTimer)
          }
        })
      },
      { threshold: 0.5 },
    )
    observer.observe(node)
  }, [markAsRead])

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

      {groups.map(([label, notifs]) => (
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
                  <button onClick={() => handleDiscuss(notif)} className="text-xs text-primary hover:underline">Discuss</button>
                  {notif.artifact_path && (
                    <button onClick={() => handleViewArtifact(notif)} className="text-xs text-muted-foreground hover:text-foreground">View artifact</button>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      ))}

      {hasMore && filtered.length > 0 && (
        <button onClick={loadMore} className="w-full py-3 text-xs text-muted-foreground hover:text-foreground">
          Load more...
        </button>
      )}

      {notifications.length === 0 && (
        <div className="text-center py-12 text-muted-foreground text-sm">
          No activity yet. Your agent will post findings here when it discovers something interesting.
        </div>
      )}

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
