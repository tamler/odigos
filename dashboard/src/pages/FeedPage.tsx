import { useState, useEffect, useCallback } from 'react'
import { get, del } from '@/lib/api'
import { Rss, Trash2, Copy, Check } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { toast } from 'sonner'

interface FeedEntry {
  id: string
  title: string
  category: string
  published_at: string
}

export default function FeedPage() {
  const [entries, setEntries] = useState<FeedEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  const feedUrl = `${window.location.origin}/feed.xml`

  const refresh = useCallback(() => {
    setLoading(true)
    get<{ entries: FeedEntry[] }>('/api/feed/entries')
      .then((data) => {
        setEntries(data.entries)
        setError(null)
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  async function handleDelete(id: string) {
    try {
      await del(`/api/feed/entries/${id}`)
      setEntries((prev) => prev.filter((e) => e.id !== id))
      toast.success('Feed entry deleted')
    } catch {
      toast.error('Failed to delete feed entry')
    }
  }

  function handleCopy() {
    navigator.clipboard.writeText(feedUrl).then(() => {
      setCopied(true)
      toast.success('Feed URL copied')
      setTimeout(() => setCopied(false), 2000)
    })
  }

  if (error) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <p className="text-destructive text-sm">Failed to load feed entries: {error}</p>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <p className="text-muted-foreground text-sm">Loading feed entries...</p>
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-4xl mx-auto px-6 py-8 space-y-6">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-lg font-semibold text-foreground">Feed</h2>
        </div>

        {/* Feed URL */}
        <div className="rounded-lg border border-border/40 p-4">
          <div className="flex items-center gap-2 mb-2">
            <Rss className="h-4 w-4 text-orange-500" />
            <h3 className="text-sm font-semibold text-foreground">Feed URL</h3>
          </div>
          <div className="flex items-center gap-2">
            <code className="flex-1 text-sm bg-muted px-3 py-2 rounded text-foreground truncate">
              {feedUrl}
            </code>
            <Button variant="ghost" size="icon" onClick={handleCopy} className="shrink-0">
              {copied ? <Check className="h-4 w-4 text-green-500" /> : <Copy className="h-4 w-4" />}
            </Button>
          </div>
        </div>

        {/* Entries */}
        {entries.length === 0 ? (
          <div className="rounded-lg border border-border/40 p-8 text-center">
            <p className="text-sm text-muted-foreground">No feed entries published yet</p>
          </div>
        ) : (
          <div className="rounded-lg border border-border/40 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/40 bg-muted/30">
                  <th className="text-left px-4 py-3 font-medium text-muted-foreground">Title</th>
                  <th className="text-left px-4 py-3 font-medium text-muted-foreground">Category</th>
                  <th className="text-left px-4 py-3 font-medium text-muted-foreground">Date</th>
                  <th className="w-12 px-4 py-3" />
                </tr>
              </thead>
              <tbody>
                {entries.map((entry) => (
                  <tr key={entry.id} className="border-b border-border/40 last:border-b-0 hover:bg-accent/30 transition-colors">
                    <td className="px-4 py-3 text-foreground">{entry.title}</td>
                    <td className="px-4 py-3">
                      <span className="inline-block px-2 py-0.5 bg-accent/50 text-xs rounded text-foreground">
                        {entry.category}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">
                      {new Date(entry.published_at).toLocaleDateString(undefined, {
                        year: 'numeric',
                        month: 'short',
                        day: 'numeric',
                      })}
                    </td>
                    <td className="px-4 py-3">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 text-muted-foreground hover:text-destructive"
                        onClick={() => handleDelete(entry.id)}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
