import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams, useNavigate, useOutletContext } from 'react-router-dom'
import { useUIStore } from '@/stores/uiStore'
import { get, post, del, patch } from '@/lib/api'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Loader2, Trash2, Share2, Globe, Maximize2, Minimize2 } from 'lucide-react'
import { MarkdownEditor } from '@/components/Editor'
import { AgentInputBar } from '@/components/AgentInputBar'
import { ShareDialog } from '@/components/ShareDialog'
import { PageTransition } from '@/components/ui/page-transition'
import { NoteSidecar } from '@/components/notes/NoteSidecar'

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
  created_at: string
}

export default function NotebookPage() {
  const { id: notebookId } = useParams<{ id: string }>()
  const navigate = useNavigate()
  let outletCtx: any = {}
  try { outletCtx = useOutletContext<any>() || {} } catch { outletCtx = {} }
  const { socketRef, setPageContextData = () => {} } = outletCtx
  const connected = useUIStore(s => s.connected)
  const agentName = useUIStore(s => s.agentName)
  const focusMode = useUIStore(s => s.focusMode)
  const setFocusMode = useUIStore(s => s.setFocusMode)

  const [notebook, setNotebook] = useState<Notebook | null>(null)
  const [entries, setEntries] = useState<NotebookEntry[]>([])
  const [content, setContent] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [shareOpen, setShareOpen] = useState(false)
  const [title, setTitle] = useState('')
  const saveTimeout = useRef<any>(null)
  const [showNotes, setShowNotes] = useState(false)
  const [replyPrefill, setReplyPrefill] = useState<string | null>(null)
  const [unreadNoteCount, setUnreadNoteCount] = useState(0)

  const loadNotebook = useCallback(async () => {
    if (!notebookId) {
      // No ID — redirect to create or pick a notebook
      try {
        const data = await get<{ notebooks: any[] }>('/api/notebooks')
        if (data.notebooks.length > 0) {
          navigate(`/notebooks/${data.notebooks[0].id}`, { replace: true })
        } else {
          const res = await post<{ id: string }>('/api/notebooks', { title: 'My Notebook' })
          navigate(`/notebooks/${res.id}`, { replace: true })
        }
      } catch {
        setLoading(false)
      }
      return
    }
    setLoading(true)
    try {
      const data = await get<any>(`/api/notebooks/${notebookId}`)
      setNotebook(data)
      setTitle(data.title)
      const sortedEntries = (data.entries || []).sort((a: any, b: any) => 
        new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
      )
      setEntries(sortedEntries)
      // Join all entries into one doc for the "Obsidian-lite" experience
      const joined = sortedEntries.map((e: any) => e.content).join('\n\n')
      setContent(joined)
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
        page: 'notebook',
        page_id: notebookId,
        page_title: notebook.title,
      })
    }
    return () => setPageContextData({})
  }, [notebook, notebookId, setPageContextData])

  useEffect(() => {
    if (!focusMode) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setFocusMode(false)
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [focusMode, setFocusMode])

  useEffect(() => {
    async function checkUnread() {
      try {
        const resp = await fetch(`/api/notebooks/${notebookId}/entries?entry_type=agent`)
        if (resp.ok) {
          const data = await resp.json()
          setUnreadNoteCount(data.unread_count || 0)
          if (data.unread_count > 0) {
            setShowNotes(true)
          }
        }
      } catch {
        // Non-critical
      }
    }
    if (notebookId) void checkUnread()
  }, [notebookId])

  const handleQuoteClick = useCallback((quote: string) => {
    const content = document.querySelector('.ProseMirror')?.textContent || ''
    const idx = content.toLowerCase().indexOf(quote.toLowerCase())
    if (idx === -1) {
      console.warn('Quoted text no longer in document')
    }
  }, [])

  const handleReplyClick = useCallback((quote: string) => {
    setReplyPrefill(`> ${quote}\n\n`)
  }, [])

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

  const saveContent = useCallback(async (newContent: string) => {
    if (!notebookId) return
    setSaving(true)
    try {
      // For "Obsidian-lite", we'll maintain the multi-entry backend but treat it as one doc.
      // We'll update the *latest* entry or create one if none exist.
      if (entries.length > 0) {
        const lastEntry = entries[entries.length - 1]
        await patch(`/api/notebooks/${notebookId}/entries/${lastEntry.id}`, { content: newContent })
        setEntries(prev => prev.map(e => e.id === lastEntry.id ? { ...e, content: newContent } : e))
      } else {
        const res = await post<NotebookEntry>(`/api/notebooks/${notebookId}/entries`, { content: newContent })
        setEntries([res])
      }
    } catch {
      toast.error('Auto-save failed')
    } finally {
      setSaving(false)
    }
  }, [notebookId, entries])

  const handleContentChange = (newContent: string) => {
    setContent(newContent)
    if (saveTimeout.current) clearTimeout(saveTimeout.current)
    saveTimeout.current = setTimeout(() => {
      saveContent(newContent)
    }, 2000)
  }

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <PageTransition className={`flex-1 flex flex-col h-full bg-background transition-all duration-300 ${focusMode ? 'fixed inset-0 z-[100] p-4 lg:p-12' : ''}`}>
      {/* Header */}
      {!focusMode && (
        <div className="flex items-center justify-between px-4 pl-14 lg:px-8 lg:pl-8 py-3 lg:py-4 border-b border-border/10 shrink-0 bg-background/50 backdrop-blur-sm sticky top-0 z-20">
          <div className="flex items-center gap-4 flex-1 min-w-0">
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              onBlur={handleUpdateTitle}
              onKeyDown={(e) => e.key === 'Enter' && handleUpdateTitle()}
              className="text-lg lg:text-xl font-bold bg-transparent border-none focus:outline-none w-full max-w-md tracking-tight placeholder:text-muted-foreground/30 truncate"
              placeholder="Untitled note"
            />
            {saving && <span className="hidden sm:inline text-[10px] font-bold uppercase tracking-widest text-muted-foreground/50 animate-pulse shrink-0">Saving...</span>}
          </div>
          
          <div className="flex items-center gap-1 shrink-0">
            <button
              onClick={() => setShowNotes(!showNotes)}
              className="text-xs text-muted-foreground hover:text-foreground px-2 py-1"
            >
              Notes{unreadNoteCount > 0 && ` (${unreadNoteCount})`}
            </button>
            <Button variant="ghost" size="icon" className="h-11 w-11 lg:h-9 lg:w-9 text-muted-foreground" onClick={() => setFocusMode(true)} title="Focus Mode (Cmd+.)">
              <Maximize2 className="h-5 w-5 lg:h-4 lg:w-4" />
            </Button>
            <Button variant="ghost" size="icon" className={`h-11 w-11 lg:h-9 lg:w-9 ${notebook?.share_token ? 'text-primary' : 'text-muted-foreground'}`} onClick={() => setShareOpen(true)} title="Share">
              {notebook?.share_token ? <Globe className="h-5 w-5 lg:h-4 lg:w-4" /> : <Share2 className="h-5 w-5 lg:h-4 lg:w-4" />}
            </Button>
            <Button variant="ghost" size="icon" className="h-11 w-11 lg:h-9 lg:w-9 text-muted-foreground hover:text-destructive" onClick={async () => {
              if (confirm('Delete this entire notebook?')) {
                await del(`/api/notebooks/${notebookId}`)
                navigate('/notebooks')
              }
            }}>
              <Trash2 className="h-5 w-5 lg:h-4 lg:w-4" />
            </Button>
          </div>
        </div>
      )}

      {/* Editor Content */}
      <div className={`flex flex-1 min-h-0 relative ${focusMode ? 'max-w-4xl mx-auto w-full rounded-2xl border border-border/10 bg-background/50 shadow-2xl overflow-hidden' : ''}`}>
        <div className={`overflow-y-auto custom-scrollbar ${showNotes && !focusMode ? 'flex-1 min-w-0' : 'w-full'}`}>
          <MarkdownEditor
            content={content}
            onChange={handleContentChange}
          />
          <div className="h-32 shrink-0" /> {/* Bottom spacer for agent bar */}
        </div>

        {/* Desktop split view */}
        {showNotes && !focusMode && (
          <div className="hidden md:block md:w-[40%] border-l border-border overflow-y-auto">
            <NoteSidecar
              notebookId={notebookId || ''}
              onQuoteClick={handleQuoteClick}
              onReplyClick={handleReplyClick}
            />
          </div>
        )}

        {/* Mobile bottom sheet */}
        {showNotes && !focusMode && (
          <div
            className="md:hidden fixed inset-x-0 bottom-0 top-16 z-40 bg-background border-t border-border overflow-y-auto rounded-t-2xl shadow-lg"
            onClick={(e) => e.target === e.currentTarget && setShowNotes(false)}
          >
            <NoteSidecar
              notebookId={notebookId || ''}
              onQuoteClick={handleQuoteClick}
              onReplyClick={handleReplyClick}
            />
          </div>
        )}
      </div>

      {/* Agent Input Bar */}
      {!focusMode && (
        <div className="absolute bottom-0 left-0 right-0 z-30 pointer-events-none">
          <div className="pointer-events-auto bg-gradient-to-t from-background via-background/95 to-transparent pt-16">
            <AgentInputBar
              agentName={agentName}
              placeholder={`Ask about "${title}"...`}
              pageContext={{
                page: 'notebook',
                page_id: notebookId,
                page_title: title,
                visible_data: content
              }}
              socketRef={socketRef}
              connected={connected}
              sttAvailable={true}
              prefill={replyPrefill}
              onPrefillConsumed={() => setReplyPrefill(null)}
            />
          </div>
        </div>
      )}

      {/* Focus Mode Exit */}
      {focusMode && (
        <button
          className="fixed top-3 right-3 z-[110] p-1.5 rounded-md text-muted-foreground/20 hover:text-foreground hover:bg-muted/80 transition-all duration-200"
          onClick={() => setFocusMode(false)}
          title="Exit Focus Mode (Esc)"
        >
          <Minimize2 className="h-3.5 w-3.5" />
        </button>
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
    </PageTransition>
  )
}
