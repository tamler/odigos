import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { get, post, del } from '@/lib/api'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Plus, ArrowLeft, Send, Trash2 } from 'lucide-react'

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

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export default function NotebookPage() {
  const { id } = useParams<{ id?: string }>()

  if (id) {
    return <NotebookEditor notebookId={id} />
  }
  return <NotebookList />
}

function NotebookList() {
  const navigate = useNavigate()
  const [notebooks, setNotebooks] = useState<Notebook[]>([])
  const [loading, setLoading] = useState(true)
  const [newTitle, setNewTitle] = useState('')
  const [creating, setCreating] = useState(false)

  const loadNotebooks = useCallback(() => {
    setLoading(true)
    get<{ notebooks: Notebook[] }>('/api/notebooks')
      .then((data) => setNotebooks(data.notebooks))
      .catch(() => toast.error('Failed to load notebooks'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { loadNotebooks() }, [loadNotebooks])

  async function handleCreate() {
    const title = newTitle.trim()
    if (!title) return
    setCreating(true)
    try {
      const nb = await post<Notebook>('/api/notebooks', { title })
      setNewTitle('')
      navigate(`/notebooks/${nb.id}`)
    } catch {
      toast.error('Failed to create notebook')
    } finally {
      setCreating(false)
    }
  }

  async function handleDelete(id: string, e: React.MouseEvent) {
    e.stopPropagation()
    try {
      await del(`/api/notebooks/${id}`)
      setNotebooks((prev) => prev.filter((n) => n.id !== id))
      toast.success('Notebook deleted')
    } catch {
      toast.error('Failed to delete notebook')
    }
  }

  return (
    <div className="flex flex-col h-full max-w-2xl mx-auto w-full px-4 py-8">
      <h1 className="text-2xl font-semibold mb-6">Notebooks</h1>

      <div className="flex gap-2 mb-6">
        <Input
          value={newTitle}
          onChange={(e) => setNewTitle(e.target.value)}
          placeholder="New notebook title..."
          onKeyDown={(e) => { if (e.key === 'Enter') handleCreate() }}
          className="flex-1"
        />
        <Button onClick={handleCreate} disabled={creating || !newTitle.trim()}>
          <Plus className="h-4 w-4 mr-1" /> Create
        </Button>
      </div>

      {loading ? (
        <div className="text-muted-foreground text-sm">Loading...</div>
      ) : notebooks.length === 0 ? (
        <div className="text-muted-foreground text-sm">No notebooks yet. Create one above.</div>
      ) : (
        <div className="space-y-2">
          {notebooks.map((n) => (
            <div
              key={n.id}
              onClick={() => navigate(`/notebooks/${n.id}`)}
              className="flex items-center justify-between px-4 py-3 rounded-md border border-border/50 hover:bg-accent/50 cursor-pointer transition-colors group"
            >
              <div>
                <div className="text-sm font-medium">{n.title}</div>
                <div className="text-xs text-muted-foreground mt-0.5">
                  {n.mode} &middot; {n.collaboration} &middot;{' '}
                  {new Date(n.updated_at + 'Z').toLocaleDateString(undefined, {
                    month: 'short', day: 'numeric', year: 'numeric',
                  })}
                </div>
              </div>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-destructive"
                onClick={(e) => handleDelete(n.id, e)}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function NotebookEditor({ notebookId }: { notebookId: string }) {
  const navigate = useNavigate()
  const [notebook, setNotebook] = useState<Notebook | null>(null)
  const [entries, setEntries] = useState<NotebookEntry[]>([])
  const [newEntry, setNewEntry] = useState('')
  const [adding, setAdding] = useState(false)
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([])
  const [chatInput, setChatInput] = useState('')
  const [chatLoading, setChatLoading] = useState(false)
  const chatEndRef = useRef<HTMLDivElement>(null)
  const entriesEndRef = useRef<HTMLDivElement>(null)

  const loadNotebook = useCallback(() => {
    get<Notebook & { entries: NotebookEntry[] }>(`/api/notebooks/${notebookId}`)
      .then((data) => {
        const { entries: loadedEntries, ...nb } = data
        setNotebook(nb)
        setEntries(loadedEntries)
      })
      .catch(() => toast.error('Failed to load notebook'))
  }, [notebookId])

  useEffect(() => { loadNotebook() }, [loadNotebook])

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chatMessages])

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

  async function handleChatSend() {
    const message = chatInput.trim()
    if (!message) return
    setChatInput('')
    setChatMessages((prev) => [...prev, { role: 'user', content: message }])
    setChatLoading(true)
    try {
      const data = await post<{ response?: string; message?: string }>('/api/agent', {
        message,
        context: { notebook_id: notebookId },
      })
      const reply = data.response || data.message || 'Done.'
      setChatMessages((prev) => [...prev, { role: 'assistant', content: reply }])
    } catch {
      setChatMessages((prev) => [
        ...prev,
        { role: 'assistant', content: 'Could not reach agent. Please try again.' },
      ])
    } finally {
      setChatLoading(false)
    }
  }

  return (
    <div className="flex h-full overflow-hidden">
      {/* Main editor panel (70%) */}
      <div className="flex flex-col flex-1 min-w-0 border-r border-border/40">
        <div className="flex items-center gap-3 px-4 py-3 border-b border-border/40 shrink-0">
          <Button variant="ghost" size="icon" onClick={() => navigate('/notebooks')} className="shrink-0">
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <h1 className="text-base font-semibold truncate">
            {notebook ? notebook.title : 'Loading...'}
          </h1>
          {notebook && (
            <span className="text-xs text-muted-foreground ml-auto">
              {notebook.mode} &middot; {notebook.collaboration}
            </span>
          )}
        </div>

        <ScrollArea className="flex-1 px-4">
          <div className="py-4 space-y-3 max-w-2xl">
            {entries.length === 0 && (
              <div className="text-muted-foreground text-sm">No entries yet. Add one below.</div>
            )}
            {entries.map((entry) => (
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
                    className="absolute top-2 right-2 h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-destructive"
                    onClick={() => handleDeleteEntry(entry.id)}
                  >
                    <Trash2 className="h-3 w-3" />
                  </Button>
                )}
              </div>
            ))}
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
            <Button onClick={handleAddEntry} disabled={adding || !newEntry.trim()} size="icon">
              <Plus className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </div>

      {/* Contextual chat panel (30%), hidden on mobile */}
      <div className="hidden md:flex flex-col w-[30%] min-w-[240px] max-w-xs">
        <div className="px-4 py-3 border-b border-border/40 shrink-0">
          <div className="text-sm font-medium">Contextual Chat</div>
          <div className="text-xs text-muted-foreground mt-0.5">Ask about this notebook</div>
        </div>

        <ScrollArea className="flex-1 px-3">
          <div className="py-3 space-y-3">
            {chatMessages.length === 0 && (
              <div className="text-xs text-muted-foreground">
                Ask the agent anything about this notebook.
              </div>
            )}
            {chatMessages.map((msg, i) => (
              <div
                key={i}
                className={`rounded-md px-3 py-2 text-sm ${
                  msg.role === 'user'
                    ? 'bg-accent ml-4'
                    : 'bg-muted/50 mr-4'
                }`}
              >
                {msg.content}
              </div>
            ))}
            {chatLoading && (
              <div className="rounded-md px-3 py-2 text-sm bg-muted/50 mr-4 text-muted-foreground animate-pulse">
                Thinking...
              </div>
            )}
            <div ref={chatEndRef} />
          </div>
        </ScrollArea>

        <div className="px-3 py-3 border-t border-border/40 shrink-0">
          <div className="flex gap-2">
            <Input
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              placeholder="Ask agent..."
              onKeyDown={(e) => { if (e.key === 'Enter') handleChatSend() }}
              className="flex-1 text-sm h-8"
            />
            <Button
              size="icon"
              className="h-8 w-8 shrink-0"
              onClick={handleChatSend}
              disabled={chatLoading || !chatInput.trim()}
            >
              <Send className="h-3 w-3" />
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
