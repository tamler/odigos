import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { useParams, useNavigate, useOutletContext } from 'react-router-dom'
import { get, post, del, patch } from '@/lib/api'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Loader2, Trash2, Plus, Share2, Globe, Maximize2, Minimize2 } from 'lucide-react'
import { MarkdownEditor } from '@/components/Editor'
import { AgentInputBar } from '@/components/AgentInputBar'
import { ShareDialog } from '@/components/ShareDialog'

interface Notebook {
  id: string
  title: string
  mode: string
  collaboration: string
  share_with_agent: number
  share_token?: string | null
  created_at: string
  updated_at: string
}

interface NotebookEntry {
  id: string
  content: string
  entry_type: string
  status: string
  mood?: string
  created_at: string
}

function EntryEditor({ 
  entry, 
  onSave, 
  onDelete 
}: { 
  entry: NotebookEntry
  onSave: (content: string) => void
  onDelete: () => void
}) {
  const [content, setContent] = useState(entry.content)
  const saveTimeout = useRef<any>(null)

  // Sync with prop changes (e.g. from other users or agent)
  useEffect(() => {
    setContent(entry.content)
  }, [entry.content])

  const handleChange = (newContent: string) => {
    setContent(newContent)
    if (saveTimeout.current) clearTimeout(saveTimeout.current)
    saveTimeout.current = setTimeout(() => {
      if (newContent !== entry.content) {
        onSave(newContent)
      }
    }, 1500)
  }

  return (
    <div className="group relative border-b border-border/10 last:border-0">
      <MarkdownEditor
        content={content}
        onChange={handleChange}
      />
      <button
        onClick={onDelete}
        className="absolute top-4 right-4 p-1 rounded-md opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-all z-10"
        title="Delete entry"
      >
        <Trash2 className="h-3.5 w-3.5" />
      </button>
    </div>
  )
}

export default function NotebookPage() {
  const { id: notebookId } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { 
    socketRef, 
    connected, 
    agentName, 
    setPageContextData,
  } = useOutletContext<any>()

  const [notebook, setNotebook] = useState<Notebook | null>(null)
  const [entries, setEntries] = useState<NotebookEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [shareOpen, setShareOpen] = useState(false)
  const [focusMode, setFocusMode] = useState(false)
  const [title, setTitle] = useState('')
  const [newEntryContent, setNewEntryContent] = useState('')
  const [creatingEntry, setCreatingEntry] = useState(false)

  const loadNotebook = useCallback(async () => {
    if (!notebookId) return
    setLoading(true)
    try {
      const data = await get<any>(`/api/notebooks/${notebookId}`)
      setNotebook(data.notebook)
      setTitle(data.notebook.title)
      setEntries(data.entries || [])
    } catch {
      toast.error('Failed to load notebook')
      navigate('/notebooks')
    } finally {
      setLoading(false)
    }
  }, [notebookId, navigate])

  useEffect(() => {
    loadNotebook()
  }, [loadNotebook])

  useEffect(() => {
    if (notebook) {
      setPageContextData({
        page_id: notebookId,
        page_title: notebook.title,
        visible_data: `${entries.length} entries. Latest content preview: "${entries[entries.length - 1]?.content.slice(0, 100)}..."`
      })
    }
    return () => setPageContextData({})
  }, [notebook, notebookId, entries, setPageContextData])

  // Focus mode keyboard shortcut (G-W5)
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === '.') {
        e.preventDefault()
        setFocusMode(prev => !prev)
      }
      if (e.key === 'Escape' && focusMode) {
        setFocusMode(false)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [focusMode])

  const handleUpdateTitle = async () => {
    if (!notebook || title === notebook.title || !title.trim()) return
    try {
      await patch(`/api/notebooks/${notebookId}`, { title: title.trim() })
      setNotebook({ ...notebook, title: title.trim() })
      toast.success('Title updated')
    } catch {
      toast.error('Failed to update title')
      setTitle(notebook.title)
    }
  }

  const handlePatchEntry = async (entryId: string, content: string) => {
    try {
      await patch(`/api/notebooks/${notebookId}/entries/${entryId}`, { content })
      setEntries(prev => prev.map(e => e.id === entryId ? { ...e, content } : e))
    } catch {
      toast.error('Failed to auto-save entry')
    }
  }

  const handleDeleteEntry = async (entryId: string) => {
    if (!confirm('Are you sure you want to delete this entry?')) return
    try {
      await del(`/api/notebooks/${notebookId}/entries/${entryId}`)
      setEntries(prev => prev.filter(e => e.id !== entryId))
      toast.success('Entry deleted')
    } catch {
      toast.error('Failed to delete entry')
    }
  }

  const handleCreateEntry = async (content: string) => {
    if (!content.trim() || creatingEntry) return
    setCreatingEntry(true)
    try {
      const res = await post<NotebookEntry>(`/api/notebooks/${notebookId}/entries`, { content })
      setEntries(prev => [...prev, res])
      setNewEntryContent('')
    } catch {
      toast.error('Failed to add entry')
    } finally {
      setCreatingEntry(false)
    }
  }

  const entriesByDate = useMemo(() => {
    const groups: Record<string, NotebookEntry[]> = {}
    entries.forEach(e => {
      const date = new Date(e.created_at + 'Z').toLocaleDateString(undefined, { 
        year: 'numeric', month: 'long', day: 'numeric' 
      })
      if (!groups[date]) groups[date] = []
      groups[date].push(e)
    })
    return Object.entries(groups)
  }, [entries])

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <div className={`flex-1 flex flex-col h-full bg-background transition-all duration-300 ${focusMode ? 'fixed inset-0 z-[100] p-4 sm:p-12 overflow-y-auto' : 'overflow-hidden'}`}>
      {/* Header */}
      {!focusMode && (
        <div className="flex items-center justify-between px-6 py-4 border-b border-border/40 shrink-0 bg-background/50 backdrop-blur-sm sticky top-0 z-20">
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onBlur={handleUpdateTitle}
            onKeyDown={(e) => e.key === 'Enter' && handleUpdateTitle()}
            className="text-xl font-bold bg-transparent border-none focus:outline-none w-full max-w-md tracking-tight placeholder:text-muted-foreground/50"
            placeholder="Untitled notebook"
          />
          
          <div className="flex items-center gap-2">
            <Button 
              variant="ghost" 
              size="icon" 
              className="h-9 w-9 text-muted-foreground" 
              onClick={() => setFocusMode(true)}
              title="Focus Mode (Cmd+.)"
            >
              <Maximize2 className="h-4 w-4" />
            </Button>
            <Button 
              variant="ghost" 
              size="icon" 
              className={`h-9 w-9 ${notebook?.share_token ? 'text-primary' : 'text-muted-foreground'}`}
              onClick={() => setShareOpen(true)}
              title="Share"
            >
              {notebook?.share_token ? <Globe className="h-4 w-4" /> : <Share2 className="h-4 w-4" />}
            </Button>
            <Button 
              variant="ghost" 
              size="icon" 
              className="h-9 w-9 text-muted-foreground hover:text-destructive"
              onClick={async () => {
                if (confirm('Delete this entire notebook?')) {
                  await del(`/api/notebooks/${notebookId}`)
                  navigate('/notebooks')
                }
              }}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        </div>
      )}

      {/* Editor Content */}
      <div className={`flex-1 overflow-y-auto custom-scrollbar ${focusMode ? 'max-w-4xl mx-auto w-full' : ''}`}>
        <div className="pb-32">
          {entriesByDate.map(([date, dateEntries]) => (
            <div key={date}>
              <div className="sticky top-0 z-10 bg-background/80 backdrop-blur-sm px-8 py-3 border-b border-border/5 flex items-center justify-between group">
                <span className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground/60">{date}</span>
                <div className="h-[1px] flex-1 mx-4 bg-border/10" />
              </div>
              {dateEntries.map(entry => (
                <EntryEditor
                  key={entry.id}
                  entry={entry}
                  onSave={(content) => handlePatchEntry(entry.id, content)}
                  onDelete={() => handleDeleteEntry(entry.id)}
                />
              ))}
            </div>
          ))}

          {/* New Entry Editor at Bottom */}
          <div className="border-t border-border/5 pt-4">
            <div className="px-8 py-2 text-[10px] font-bold uppercase tracking-widest text-primary/40">New Entry</div>
            <MarkdownEditor
              content={newEntryContent}
              onChange={setNewEntryContent}
            />
            {newEntryContent.trim() && (
              <div className="px-8 pb-8 flex justify-end">
                <Button 
                  size="sm" 
                  onClick={() => handleCreateEntry(newEntryContent)}
                  disabled={creatingEntry}
                >
                  {creatingEntry ? <Loader2 className="h-3 w-3 animate-spin mr-2" /> : <Plus className="h-3 w-3 mr-2" />}
                  Save Entry
                </Button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Agent Input Bar (G-W3) */}
      {!focusMode && (
        <div className="absolute bottom-0 left-0 right-0 z-30 pointer-events-none">
          <div className="pointer-events-auto bg-gradient-to-t from-background via-background/90 to-transparent pt-12">
            <AgentInputBar
              agentName={agentName}
              placeholder="Ask about this notebook..."
              pageContext={{
                page: 'notebook',
                page_id: notebookId,
                page_title: notebook?.title,
                visible_data: `${entries.length} entries found.`
              }}
              socketRef={socketRef}
              connected={connected}
              sttAvailable={true} // assume true for now, can refine later
            />
          </div>
        </div>
      )}

      {/* Focus Mode Exit */}
      {focusMode && (
        <Button 
          variant="secondary" 
          size="sm" 
          className="fixed top-6 right-6 z-[110] shadow-lg rounded-full"
          onClick={() => setFocusMode(false)}
        >
          <Minimize2 className="h-4 w-4 mr-2" />
          Exit Focus
        </Button>
      )}

      <ShareDialog
        type="notebook"
        id={notebookId || ''}
        isOpen={shareOpen}
        onClose={() => {
          setShareOpen(false)
          loadNotebook()
        }}
        initialShareToken={notebook?.share_token}
      />
    </div>
  )
}
