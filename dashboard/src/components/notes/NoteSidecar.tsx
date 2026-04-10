import { useCallback, useEffect, useRef, useState } from 'react'
import { NoteEntry, type NotebookEntry } from './NoteEntry'
import { NoteTableOfContents } from './NoteTableOfContents'

interface NoteSidecarProps {
  notebookId: string
  onQuoteClick?: (quote: string) => void
  onReplyClick?: (quote: string) => void
}

export function NoteSidecar({ notebookId, onQuoteClick, onReplyClick }: NoteSidecarProps) {
  const [entries, setEntries] = useState<NotebookEntry[]>([])
  const [showDead, setShowDead] = useState(false)
  const [loading, setLoading] = useState(true)
  const [unreadCount, setUnreadCount] = useState(0)
  const observersRef = useRef<Map<string, IntersectionObserver>>(new Map())

  const fetchEntries = useCallback(async () => {
    try {
      const url = `/api/notebooks/${notebookId}/entries?entry_type=agent&include_dead=${showDead}`
      const resp = await fetch(url)
      if (!resp.ok) {
        setLoading(false)
        return
      }
      const data = await resp.json()
      setEntries(data.entries || [])
      setUnreadCount(data.unread_count || 0)
      setLoading(false)
    } catch {
      setLoading(false)
    }
  }, [notebookId, showDead])

  useEffect(() => {
    void fetchEntries()
  }, [fetchEntries])

  // Refetch on window focus
  useEffect(() => {
    const handleFocus = () => void fetchEntries()
    window.addEventListener('focus', handleFocus)
    return () => window.removeEventListener('focus', handleFocus)
  }, [fetchEntries])

  const markViewed = useCallback(
    async (entryId: string) => {
      try {
        await fetch(
          `/api/notebooks/${notebookId}/entries/${entryId}/view`,
          { method: 'POST' },
        )
      } catch {
        // Non-critical
      }
    },
    [notebookId],
  )

  const markReadRef = useCallback(
    (node: HTMLDivElement | null) => {
      if (!node) return
      const id = node.dataset.noteId
      if (!id) return
      const prev = observersRef.current.get(id)
      if (prev) prev.disconnect()

      const observer = new IntersectionObserver(
        (entries) => {
          entries.forEach((entry) => {
            const el = entry.target as HTMLDivElement & {
              _readTimer?: ReturnType<typeof setTimeout>
            }
            if (entry.isIntersecting) {
              el._readTimer = setTimeout(() => void markViewed(id), 500)
            } else if (el._readTimer) {
              clearTimeout(el._readTimer)
            }
          })
        },
        { threshold: 0.5 },
      )
      observer.observe(node)
      observersRef.current.set(id, observer)
    },
    [markViewed],
  )

  useEffect(() => {
    return () => {
      observersRef.current.forEach((obs) => obs.disconnect())
      observersRef.current.clear()
    }
  }, [])

  const handleMarkAllViewed = async () => {
    try {
      await fetch(
        `/api/notebooks/${notebookId}/mark-all-viewed?entry_type=agent`,
        { method: 'POST' },
      )
      void fetchEntries()
    } catch {
      // Non-critical
    }
  }

  const handleToggleDead = async (entry: NotebookEntry) => {
    const newStatus = entry.status === 'dead' ? 'active' : 'dead'
    try {
      await fetch(
        `/api/notebooks/${notebookId}/entries/${entry.id}`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status: newStatus }),
        },
      )
      void fetchEntries()
    } catch {
      // Non-critical
    }
  }

  const handleReply = (entry: NotebookEntry) => {
    if (!entry.quote) return
    onReplyClick?.(entry.quote)
  }

  const handleJumpTo = (entryId: string) => {
    const el = document.querySelector(`[data-note-id="${entryId}"]`)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      el.classList.add('ring-2', 'ring-primary', 'ring-offset-2')
      setTimeout(() => {
        el.classList.remove('ring-2', 'ring-primary', 'ring-offset-2')
      }, 1500)
    }
  }

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between p-3 border-b border-border">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold">Notes</h2>
          {unreadCount > 0 && (
            <span className="text-[10px] px-1.5 py-0.5 rounded-sm bg-purple-500/10 text-purple-400">
              {unreadCount} new
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 text-xs">
          <button
            onClick={() => setShowDead(!showDead)}
            className="text-muted-foreground hover:text-foreground"
          >
            {showDead ? 'hide dead' : 'show dead'}
          </button>
          {unreadCount > 0 && (
            <button
              onClick={handleMarkAllViewed}
              className="text-muted-foreground hover:text-foreground"
            >
              mark all read
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-3">
        {loading ? (
          <div className="text-sm text-muted-foreground">Loading...</div>
        ) : entries.length === 0 ? (
          <div className="text-sm text-muted-foreground">
            The agent hasn't reviewed this notebook yet. Share with agent and it will review during idle time.
          </div>
        ) : (
          <>
            <NoteTableOfContents entries={entries} onJumpTo={handleJumpTo} />
            {entries.map((entry) => (
              <div
                key={entry.id}
                ref={!entry.viewed_at ? markReadRef : undefined}
                data-note-id={entry.id}
              >
                <NoteEntry
                  entry={entry}
                  onQuoteClick={onQuoteClick}
                  onReplyClick={handleReply}
                  onToggleDead={handleToggleDead}
                />
              </div>
            ))}
          </>
        )}
      </div>
    </div>
  )
}
