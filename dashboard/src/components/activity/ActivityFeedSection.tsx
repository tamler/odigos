import { useEffect, useCallback, useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import Markdown from 'react-markdown'
import { useNotificationStore, type Notification } from '@/stores/notificationStore'
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

export function ActivityFeedSection() {
  const { notifications, fetchNotifications, markAsRead, discuss } = useNotificationStore()
  const navigate = useNavigate()
  const [filter, setFilter] = useState<string>('all')
  const [showAll, setShowAll] = useState(false)
  const [artifactContent, setArtifactContent] = useState<string | null>(null)
  const [artifactTitle, setArtifactTitle] = useState('')
  const observersRef = useRef<Map<string, IntersectionObserver>>(new Map())

  useEffect(() => {
    void fetchNotifications(false, 20, 0)
  }, [fetchNotifications])

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
    void markAsRead(notif.id)
  }

  const markReadRef = useCallback(
    (node: HTMLDivElement | null) => {
      if (!node) return
      const id = node.dataset.notifId
      if (!id) return
      // Cleanup previous observer for this node if any
      const prev = observersRef.current.get(id)
      if (prev) prev.disconnect()

      const observer = new IntersectionObserver(
        (entries) => {
          entries.forEach((entry) => {
            const el = entry.target as HTMLDivElement & {
              _readTimer?: ReturnType<typeof setTimeout>
            }
            if (entry.isIntersecting) {
              el._readTimer = setTimeout(() => void markAsRead(id), 500)
            } else if (el._readTimer) {
              clearTimeout(el._readTimer)
            }
          })
        },
        { threshold: 0.5 }
      )
      observer.observe(node)
      observersRef.current.set(id, observer)
    },
    [markAsRead]
  )

  useEffect(() => {
    return () => {
      observersRef.current.forEach((obs) => obs.disconnect())
      observersRef.current.clear()
    }
  }, [])

  const filtered = filter === 'all'
    ? notifications
    : notifications.filter((n) => n.type === filter)

  const visible = showAll ? filtered : filtered.slice(0, 5)
  const groups = groupByDate(visible)

  return (
    <section className="mb-6">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-[10px] font-semibold tracking-widest text-muted-foreground uppercase">
          Recent Activity
        </h2>
        <select
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="text-xs bg-transparent text-muted-foreground border border-border rounded px-2 py-1"
        >
          <option value="all">All</option>
          <option value="finding">Finding</option>
          <option value="suggestion">Suggestion</option>
          <option value="status">Completed</option>
          <option value="alert">Alert</option>
        </select>
      </div>

      {groups.length === 0 ? (
        <div className="text-sm text-muted-foreground">
          No activity yet. Your agent will post findings here when it discovers something interesting.
        </div>
      ) : (
        groups.map(([label, notifs]) => (
          <div key={label} className="mb-4">
            <div className="text-[10px] font-semibold text-muted-foreground tracking-widest mb-2 uppercase">
              {label}
            </div>
            {notifs.map((notif) => {
              const config = TYPE_CONFIG[notif.type] || TYPE_CONFIG.status
              return (
                <div
                  key={notif.id}
                  ref={!notif.read ? markReadRef : undefined}
                  data-notif-id={notif.id}
                  className={`bg-card rounded-xl p-3 mb-2 border border-border transition-opacity ${
                    notif.read ? 'opacity-60' : ''
                  }`}
                >
                  <div className="flex items-center gap-2 mb-1">
                    <span
                      className={`text-[10px] font-semibold tracking-wide ${config.color}`}
                    >
                      {config.label}
                    </span>
                    <span className="text-[10px] text-muted-foreground">
                      {new Date(notif.created_at).toLocaleTimeString([], {
                        hour: '2-digit',
                        minute: '2-digit',
                      })}
                    </span>
                  </div>
                  <div className="text-sm font-medium">{notif.title}</div>
                  {notif.body && (
                    <div className="text-xs text-muted-foreground mt-1 line-clamp-3">
                      {notif.body}
                    </div>
                  )}
                  <div className="flex gap-3 mt-2">
                    <button
                      onClick={() => void handleDiscuss(notif)}
                      className="text-xs text-primary hover:underline"
                    >
                      Discuss
                    </button>
                    {notif.artifact_path && (
                      <button
                        onClick={() => void handleViewArtifact(notif)}
                        className="text-xs text-muted-foreground hover:text-foreground"
                      >
                        View artifact
                      </button>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        ))
      )}

      {filtered.length > 5 && (
        <button
          onClick={() => setShowAll(!showAll)}
          className="w-full py-2 text-xs text-muted-foreground hover:text-foreground"
        >
          {showAll ? 'show less' : `show all (${filtered.length})`}
        </button>
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
    </section>
  )
}
