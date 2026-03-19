import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams, useNavigate, useOutletContext } from 'react-router-dom'
import { get, post, del } from '@/lib/api'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Skeleton } from '@/components/ui/skeleton'
import { Plus, Trash2, BookOpen } from 'lucide-react'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'

interface Notebook {
  id: string
  title: string
  mode: string
  collaboration: string
  share_with_agent: number
  created_at: string
  updated_at: string
}

interface NotebookEntry {
  id: string
  notebook_id: string
  content: string
  entry_type: string
  status: string
  mood: string | null
  created_at: string
}



export default function NotebookPage() {
  const { id } = useParams<{ id?: string }>()

  if (id) {
    return <NotebookEditor notebookId={id} />
  }
  return <NotebookAutoRedirect />
}

function NotebookAutoRedirect() {
  const navigate = useNavigate()
  useEffect(() => {
    get<{ notebooks: Notebook[] }>('/api/notebooks')
      .then((data) => {
        if (data.notebooks.length === 0) {
          post<Notebook>('/api/notebooks', { title: 'My Notebook' })
            .then(nb => navigate(`/notebooks/${nb.id}`, { replace: true }))
        } else {
          const latest = data.notebooks.sort((a,b) => new Date(b.updated_at + 'Z').getTime() - new Date(a.updated_at + 'Z').getTime())[0]
          navigate(`/notebooks/${latest.id}`, { replace: true })
        }
      })
      .catch(() => {})
  }, [navigate])
  return <div className="p-8 text-sm text-muted-foreground animate-pulse">Loading workspace...</div>
}

function NotebookEditor({ notebookId }: { notebookId: string }) {
  const navigate = useNavigate()
  const [notebook, setNotebook] = useState<Notebook | null>(null)
  const [notebooksList, setNotebooksList] = useState<Notebook[]>([])
  const [entries, setEntries] = useState<NotebookEntry[]>([])
  const [newEntry, setNewEntry] = useState('')
  const [adding, setAdding] = useState(false)
  const [loading, setLoading] = useState(true)
  const { setChatPanelOpen, setChatContext } = useOutletContext<any>()
  const entriesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    get<{ notebooks: Notebook[] }>('/api/notebooks').then(data => {
      setNotebooksList(data.notebooks.sort((a,b) => new Date(b.updated_at + 'Z').getTime() - new Date(a.updated_at + 'Z').getTime()))
    }).catch(() => {})
  }, [notebookId])

  const loadNotebook = useCallback(() => {
    setLoading(true)
    get<Notebook & { entries: NotebookEntry[] }>(`/api/notebooks/${notebookId}`)
      .then((data) => {
        const { entries: loadedEntries, ...nb } = data
        setNotebook(nb)
        setEntries(loadedEntries)
      })
      .catch(() => toast.error('Failed to load notebook'))
      .finally(() => setLoading(false))
  }, [notebookId])

  useEffect(() => { loadNotebook() }, [loadNotebook])

  useEffect(() => {
    entriesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [entries])

  async function handleAddEntry() {
    const content = newEntry.trim()
    if (!content) return
    setAdding(true)
    try {
      const entry = await post<NotebookEntry>(`/api/notebooks/${notebookId}/entries`, {
        content,
        entry_type: 'user',
      })
      setEntries((prev) => [...prev, entry])
      setNewEntry('')
    } catch {
      toast.error('Failed to add entry')
    } finally {
      setAdding(false)
    }
  }

  async function handleDeleteEntry(entryId: string) {
    try {
      await del(`/api/notebooks/${notebookId}/entries/${entryId}`)
      setEntries((prev) => prev.filter((e) => e.id !== entryId))
    } catch {
      toast.error('Failed to delete entry')
    }
  }

  async function handleAcceptSuggestion(entryId: string) {
    try {
      const updated = await post<NotebookEntry>(`/api/notebooks/${notebookId}/entries/${entryId}/accept`, {})
      setEntries((prev) =>
        prev.map((e) => e.id === entryId ? updated : e)
      )
    } catch {
      toast.error('Failed to accept suggestion')
    }
  }

  async function handleRejectSuggestion(entryId: string) {
    try {
      await post(`/api/notebooks/${notebookId}/entries/${entryId}/reject`, {})
      setEntries((prev) => prev.filter((e) => e.id !== entryId))
    } catch {
      toast.error('Failed to reject suggestion')
    }
  }

  return (
    <div className="flex h-full overflow-hidden">
      {/* Main editor panel (70%) */}
      <div className="flex flex-col flex-1 min-w-0 border-r border-border/40">
        <div className="flex items-center gap-3 px-4 py-3 border-b border-border/40 shrink-0">
          <DropdownMenu>
            <DropdownMenuTrigger>
              <Button variant="ghost" className="h-8 px-2 flex items-center gap-2 max-w-[200px] sm:max-w-[300px]">
                <BookOpen className="h-4 w-4 shrink-0" />
                <span className="truncate">{notebook ? notebook.title : 'Loading...'}</span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="w-56">
              <ScrollArea className="max-h-[300px]">
                {notebooksList.map(nb => (
                  <DropdownMenuItem key={nb.id} onClick={() => navigate(`/notebooks/${nb.id}`)}>
                    {nb.title}
                  </DropdownMenuItem>
                ))}
              </ScrollArea>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={async () => {
                try {
                  const nb = await post<Notebook>('/api/notebooks', { title: 'New Notebook' })
                  navigate(`/notebooks/${nb.id}`)
                } catch {
                  toast.error('Failed to create notebook')
                }
              }}>
                <Plus className="h-4 w-4 mr-2" />
                New Notebook
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>

          {/* Delete Button */}
          {notebook && (
            <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground hover:text-destructive" onClick={async () => {
              try {
                await del(`/api/notebooks/${notebookId}`)
                toast.success('Notebook deleted')
                navigate('/notebooks')
              } catch {
                toast.error('Failed to delete notebook')
              }
            }}>
              <Trash2 className="h-4 w-4" />
            </Button>
          )}

          {notebook && (
            <span className="text-xs text-muted-foreground ml-auto">
              {notebook.mode} &middot; {notebook.collaboration}
            </span>
          )}
          <Button variant="outline" size="sm" className="ml-2" onClick={() => {
            setChatContext({ notebook_id: notebookId })
            setChatPanelOpen(true)
          }}>
            Ask Agent
          </Button>
        </div>

        <ScrollArea className="flex-1 px-4">
          <div className="py-4 space-y-3 max-w-2xl">
            {loading ? (
              Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-20 w-full rounded-md" />
              ))
            ) : entries.length === 0 ? (
              <div className="text-muted-foreground text-sm">No entries yet. Add one below.</div>
            ) : (
              entries.map((entry) => (
                <div
                  key={entry.id}
                className={`group relative rounded-md border px-4 py-3 text-sm ${
                  entry.entry_type === 'agent_suggestion'
                    ? 'border-blue-500/40 bg-blue-500/5'
                    : entry.entry_type === 'agent'
                    ? 'border-primary/30 bg-primary/5'
                    : 'border-border/50'
                }`}
              >
                {entry.entry_type === 'agent_suggestion' && (
                  <div className="text-xs text-blue-400 mb-1 font-medium">Agent suggestion</div>
                )}
                {entry.entry_type === 'agent' && (
                  <div className="text-xs text-primary/60 mb-1 font-medium">Agent</div>
                )}
                {entry.mood && (
                  <div className="text-xs text-muted-foreground mb-1">{entry.mood}</div>
                )}
                <div className="whitespace-pre-wrap leading-relaxed">{entry.content}</div>
                <div className="text-xs text-muted-foreground mt-2">
                  {new Date(entry.created_at + 'Z').toLocaleString(undefined, {
                    month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
                  })}
                </div>
                {entry.entry_type === 'agent_suggestion' && entry.status === 'pending' ? (
                  <div className="flex gap-2 mt-2">
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-7 text-xs"
                      onClick={() => handleAcceptSuggestion(entry.id)}
                    >
                      Accept
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-7 text-xs text-muted-foreground"
                      onClick={() => handleRejectSuggestion(entry.id)}
                    >
                      Reject
                    </Button>
                  </div>
                ) : (
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label="Delete entry"
                    className="absolute top-2 right-2 h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-destructive"
                    onClick={() => handleDeleteEntry(entry.id)}
                  >
                    <Trash2 className="h-3 w-3" />
                  </Button>
                )}
              </div>
            )))}
            <div ref={entriesEndRef} />
          </div>
        </ScrollArea>

        <div className="px-4 py-3 border-t border-border/40 shrink-0">
          <div className="flex gap-2 max-w-2xl">
            <Input
              value={newEntry}
              onChange={(e) => setNewEntry(e.target.value)}
              placeholder="Add a note..."
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) handleAddEntry() }}
              className="flex-1"
            />
            <Button onClick={handleAddEntry} disabled={adding || !newEntry.trim()} size="icon" aria-label="Add entry">
              <Plus className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
