import { useState, useEffect, useCallback, useRef, memo } from 'react'
import { Outlet, useNavigate, useSearchParams, useLocation } from 'react-router-dom'
import { 
  Settings, 
  PanelLeftClose, 
  PanelLeft, 
  Plus, 
  Pencil, 
  Trash2, 
  Check, 
  X, 
  Download, 
  MoreHorizontal, 
  Menu,
  MessageCircle,
  Volume2,
  Zap,
  Network,
  Puzzle,
  TrendingUp,
  BarChart3,
  Database,
  FileText,
  Terminal,
  User,
  ArrowLeft,
  Link as LinkIcon,
  Rss,
  Eye,
  Columns3,
  Image as ImageIcon,
  Upload
} from 'lucide-react'
import { ChatPanel } from '@/components/ChatPanel'
import { ArtifactPreview } from '@/components/ArtifactPreview'
import { QuickSwitcher } from '@/components/QuickSwitcher'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { TooltipProvider } from '@/components/ui/tooltip'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { get, patch, del, post, uploadFile } from '@/lib/api'
import { ChatSocket } from '@/lib/ws'
import { toast } from 'sonner'
import { executeActions, UIAction } from '@/lib/actions'
import { useTheme } from 'next-themes'
import { stripForTTS, shouldPlayTTS } from '@/lib/tts-filter'
import { subscribeToPush } from '@/lib/push'
import { Artifact } from '@/components/ArtifactCard'

interface Conversation {
  id: string
  started_at: string
  last_message_at: string | null
  title?: string | null
  message_count: number
}

const SETTINGS_SECTIONS = [
  { id: 'general', label: 'General', icon: Settings },
  { id: 'account', label: 'Account', icon: User },
  { id: 'voice', label: 'Voice', icon: Volume2 },
  { id: 'skills', label: 'Skills', icon: Zap },
  { id: 'prompts', label: 'Prompts', icon: Terminal },
  { id: 'evolution', label: 'Evolution', icon: TrendingUp },
  { id: 'agents', label: 'Agents', icon: User },
  { id: 'plugins', label: 'Plugins', icon: Puzzle },
  { id: 'documents', label: 'Documents', icon: FileText },
  { id: 'integrations', label: 'Integrations', icon: Zap },
  { id: 'mesh', label: 'Mesh', icon: Network },
  { id: 'data', label: 'Data', icon: Database },
  { id: 'analytics', label: 'Analytics', icon: BarChart3 },
  { id: 'connections', label: 'Connections', icon: LinkIcon },
  { id: 'peers', label: 'Peers', icon: Network },
  { id: 'feed', label: 'Feed', icon: Rss },
  { id: 'inspector', label: 'Inspector', icon: Eye },
]

export interface AssistantConfig {
  enabled: boolean
  show_transcript: boolean
  text_input: boolean
  voice_input: boolean
  auto_read: boolean
  position: 'bottom-right' | 'bottom-left'
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  timestamp: string
  attachments?: { id: string; filename: string; size: number }[]
  actions?: UIAction[]
}

const AppSidebar = memo(({
  collapsed, setCollapsed, sidebarOpen, setSidebarOpen, 
  isMobile, searchQuery, setSearchQuery, 
  isSettings, isNotebook, isKanban, isChat, isImages, currentTab,
  agentName, notebooks, boards, images, filteredConversations,
  activeId, handleNewChat, handleSelectConversation, handleSelectImage,
  startRename, editingId, editTitle, setEditTitle,
  confirmRename, handleExport, handleDelete, displayTitle, navigate, location
}: any) => {
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleUploadClick = () => {
    fileInputRef.current?.click()
  }

  const onFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    try {
      await uploadFile(file)
      toast.success('Image uploaded')
      window.location.reload() // Simple way to refresh for now
    } catch {
      toast.error('Upload failed')
    }
  }

  return (
    <aside className={`fixed inset-y-0 left-0 z-40 w-64 flex flex-col bg-background transition-all duration-200 ease-in-out ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'} lg:static lg:translate-x-0 ${collapsed && !isSettings ? 'lg:w-14' : 'lg:w-64'}`}>
      <div className="flex flex-col gap-2 p-3 mb-2">
        <div className="flex items-center gap-1 mb-2 px-1 min-h-[32px]">
          <Button variant="ghost" size="icon" aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"} onClick={() => setCollapsed(!collapsed)} className="shrink-0 h-8 w-8">
            {collapsed ? <PanelLeft className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
          </Button>
          {!collapsed && (
            <button onClick={() => navigate('/')} className="text-lg font-bold tracking-tight px-2 hover:text-primary transition-colors text-left truncate">{agentName}</button>
          )}
        </div>

        {(!collapsed || isSettings) && !isSettings && (
          <div className="flex items-center gap-1 px-1 pb-2">
            <button onClick={() => navigate('/')} className={`flex-1 p-2 rounded-lg flex items-center justify-center transition-colors ${isChat ? 'bg-primary/10 text-primary shadow-inner' : 'text-muted-foreground hover:bg-muted'}`} title="Chat"><MessageCircle className="h-4 w-4" /></button>
            <button onClick={() => navigate('/notebooks')} className={`flex-1 p-2 rounded-lg flex items-center justify-center transition-colors ${isNotebook ? 'bg-primary/10 text-primary shadow-inner' : 'text-muted-foreground hover:bg-muted'}`} title="Notebooks"><FileText className="h-4 w-4" /></button>
            <button onClick={() => navigate('/kanban')} className={`flex-1 p-2 rounded-lg flex items-center justify-center transition-colors ${isKanban ? 'bg-primary/10 text-primary shadow-inner' : 'text-muted-foreground hover:bg-muted'}`} title="Boards"><Columns3 className="h-4 w-4" /></button>
            <button onClick={() => navigate('/images')} className={`flex-1 p-2 rounded-lg flex items-center justify-center transition-colors ${isImages ? 'bg-primary/10 text-primary shadow-inner' : 'text-muted-foreground hover:bg-muted'}`} title="Images"><ImageIcon className="h-4 w-4" /></button>
          </div>
        )}

        {(!collapsed || isMobile) && (isChat || isImages) && (
          <div className="px-1">
            {isChat ? (
              <Button variant="secondary" size="sm" className="w-full justify-start gap-2 h-8 rounded-lg shadow-sm mb-2" onClick={handleNewChat}>
                <Plus className="h-4 w-4" /> New Chat
              </Button>
            ) : (
              <>
                <Button variant="secondary" size="sm" className="w-full justify-start gap-2 h-8 rounded-lg shadow-sm mb-2" onClick={handleUploadClick}>
                  <Upload className="h-4 w-4" /> Upload Image
                </Button>
                <input type="file" ref={fileInputRef} className="hidden" accept="image/*" onChange={onFileChange} />
              </>
            )}
          </div>
        )}
      </div>

      {!collapsed && isChat && (
        <div className="px-3 pb-2 pt-1 mb-2 relative group">
          <Input placeholder="Search..." value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} className="h-8 text-xs bg-muted/40 focus-visible:ring-1 border-none rounded-lg pr-8" />
          <kbd className="absolute right-5 top-1/2 -translate-y-1/2 pointer-events-none hidden group-focus-within:inline-flex h-4 select-none items-center gap-1 rounded border bg-muted px-1 font-mono text-[8px] font-medium text-muted-foreground opacity-100">⌘K</kbd>
        </div>
      )}

      {!collapsed && (
        <ScrollArea className="flex-1 px-3">
          <div className="space-y-0.5 pb-4">
            {isSettings ? (
              SETTINGS_SECTIONS.map((s) => (
                <button key={s.id} onClick={() => { navigate(`/settings/${s.id}`); setSidebarOpen(false) }} className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-colors ${currentTab === s.id ? 'bg-accent text-accent-foreground font-medium shadow-sm' : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground'}`}><s.icon className="h-4 w-4 shrink-0" /><span>{s.label}</span></button>
              ))
            ) : isNotebook ? (
              <div className="space-y-1">
                {notebooks.map((nb: any) => (
                  <button key={nb.id} onClick={() => { navigate(`/notebooks/${nb.id}`); setSidebarOpen(false) }} className={`w-full text-left px-3 py-2 rounded-lg text-sm truncate transition-colors ${location.pathname.includes(nb.id) ? 'bg-primary/10 text-primary font-bold shadow-sm' : 'text-muted-foreground hover:bg-accent/50'}`}>{nb.title}</button>
                ))}
              </div>
            ) : isKanban ? (
              <div className="space-y-1">
                {boards.map((b: any) => (
                  <button key={b.id} onClick={() => { navigate(`/kanban/${b.id}`); setSidebarOpen(false) }} className={`w-full text-left px-3 py-2 rounded-lg text-sm truncate transition-colors ${location.pathname.includes(b.id) ? 'bg-primary/10 text-primary font-bold shadow-sm' : 'text-muted-foreground hover:bg-accent/50'}`}>{b.title}</button>
                ))}
              </div>
            ) : isImages ? (
              <div className="grid grid-cols-2 gap-2 px-1">
                {images.map((img: any) => (
                  <button 
                    key={img.id} 
                    onClick={() => handleSelectImage(img.id)}
                    className={`aspect-square rounded-lg border overflow-hidden transition-all ${activeId === img.id ? 'border-primary ring-2 ring-primary/20' : 'border-border/40 hover:border-border'}`}
                  >
                    <img src={`/api/files/${img.filename}`} alt={img.filename} className="w-full h-full object-cover" loading="lazy" />
                  </button>
                ))}
              </div>
            ) : (
              filteredConversations.length === 0 ? (
                <div className="px-3 py-6 mt-4 text-center text-xs text-muted-foreground italic">No conversations found</div>
              ) : (
                filteredConversations.map((c: any) => (
                  <div key={c.id} className="group relative mb-0.5">
                    {editingId === c.id ? (
                      <div className="flex items-center gap-1 px-1 py-1">
                        <Input
                          autoFocus
                          value={editTitle}
                          onChange={(e) => setEditTitle(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') confirmRename()
                            if (e.key === 'Escape') startRename(null)
                          }}
                          className="h-7 text-sm"
                        />
                        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={confirmRename}><Check className="h-3 w-3" /></Button>
                        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => startRename(null)}><X className="h-3 w-3" /></Button>
                      </div>
                    ) : (
                      <button onClick={() => handleSelectConversation(c.id)} className={`w-full text-left px-3 py-2 min-h-[40px] rounded-lg text-sm truncate transition-colors pr-8 ${activeId === c.id ? 'bg-primary/10 text-primary font-bold shadow-sm' : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground'}`}>{displayTitle(c)}</button>
                    )}
                    {activeId === c.id && editingId !== c.id && (
                      <div className="absolute right-1 top-1/2 -translate-y-1/2">
                        <DropdownMenu>
                          <DropdownMenuTrigger><Button variant="ghost" size="icon" className="h-7 w-7 text-primary hover:bg-primary/20"><MoreHorizontal className="h-3.5 w-3.5" /></Button></DropdownMenuTrigger>
                          <DropdownMenuContent align="end" className="w-40 rounded-xl shadow-xl">
                            <DropdownMenuItem onClick={() => startRename(c)}><Pencil className="h-3.5 w-3.5 mr-2" /> Rename</DropdownMenuItem>
                            <DropdownMenuItem onClick={() => handleExport(c.id, 'markdown')}><Download className="h-3.5 w-3.5 mr-2" /> Export</DropdownMenuItem>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem onClick={() => handleDelete(c.id)} className="text-destructive"><Trash2 className="h-3.5 w-3.5 mr-2" /> Delete</DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
                    )}
                  </div>
                ))
              )
            )}
          </div>
        </ScrollArea>
      )}

      <div className="p-3 mt-auto border-t border-border/10">
        <button 
          onClick={() => { setSidebarOpen(false); navigate(isSettings ? '/' : '/settings') }} 
          className={`flex items-center gap-3 w-full p-2.5 rounded-xl transition-all ${isSettings ? 'bg-primary text-primary-foreground shadow-lg shadow-primary/20' : 'text-muted-foreground hover:bg-muted'}`}
          title={isSettings ? "Back to Chat" : "Settings"}
        >
          {isSettings ? <MessageCircle className="h-4 w-4 shrink-0" /> : <Settings className="h-4 w-4 shrink-0" />}
          {!collapsed && <span className="text-sm font-bold">{isSettings ? 'Back to Chat' : 'Settings'}</span>}
        </button>
      </div>
    </aside>
  )
})

AppSidebar.displayName = 'AppSidebar'

export default function AppLayout() {
  const [collapsed, setCollapsed] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [isMobile, setIsMobile] = useState(typeof window !== 'undefined' ? window.innerWidth < 1024 : false)
  const [searchQuery, setSearchQuery] = useState('')
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [notebooks, setNotebooks] = useState<{ id: string; title: string; updated_at: string }[]>([])
  const [boards, setBoards] = useState<{ id: string; title: string; updated_at: string }[]>([])
  const [images, setImages] = useState<Artifact[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [streamingContent, setStreamingContent] = useState('')
  const [thinking, setThinking] = useState(false)
  const [status, setStatus] = useState<string | null>(null)
  const [queuedCount, setQueuedCount] = useState(0)
  const [suggestedActions, setSuggestedActions] = useState<string[]>([])
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editTitle, setEditTitle] = useState('')
  const [connected, setConnected] = useState(false)
  const [hasNewEmail, setHasNewEmail] = useState(false)
  const [chatPanelOpen, setChatPanelOpen] = useState(false)
  const [artifactPanelOpen, setArtifactPanelOpen] = useState(false)
  const [activeArtifactId, setActiveArtifactId] = useState<string | null>(null)
  const [focusMode, setFocusMode] = useState(false)
  const [switcherOpen, setSwitcherOpen] = useState(false)
  const [chatContext, setChatContext] = useState<Record<string, string> | undefined>(undefined)
  const editInputRef = useRef<HTMLInputElement>(null)
  const socketRef = useRef<ChatSocket | null>(null)
  const navigate = useNavigate()
  const navigateRef = useRef(navigate)
  navigateRef.current = navigate
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const [agentName, setAgentName] = useState('Odigos')
  const { setTheme } = useTheme()
  const setThemeRef = useRef(setTheme)
  setThemeRef.current = setTheme
  const currentAudioRef = useRef<HTMLAudioElement | null>(null)
  const pendingTitles = useRef<Record<string, string>>({})

  const [isTTSPlaying, setIsTTSPlaying] = useState(false)
  const activeIdRef = useRef(activeId)

  useEffect(() => {
    activeIdRef.current = activeId
  }, [activeId])

  const playTTS = useCallback(async (text: string) => {
    if (currentAudioRef.current) {
      currentAudioRef.current.pause()
      currentAudioRef.current.src = ''
      currentAudioRef.current = null
      setIsTTSPlaying(false)
    }
    if (!text) return
    try {
      const res = await fetch(`/api/audio/speak?text=${encodeURIComponent(text)}`, {
        credentials: 'include',
      })
      if (!res.ok) return
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const audio = new Audio(url)
      currentAudioRef.current = audio
      setIsTTSPlaying(true)
      audio.onended = () => {
        URL.revokeObjectURL(url)
        currentAudioRef.current = null
        setIsTTSPlaying(false)
      }
      audio.play()
    } catch {
      setIsTTSPlaying(false)
    }
  }, [])

  const stopTTS = useCallback(() => {
    if (currentAudioRef.current) {
      currentAudioRef.current.pause()
      currentAudioRef.current.src = ''
      currentAudioRef.current = null
    }
    setIsTTSPlaying(false)
  }, [])

  useEffect(() => {
    const handleResize = () => setIsMobile(window.innerWidth < 1024)
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  // Keyboard shortcuts (G14, G-W3)
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        setSwitcherOpen(true)
        return
      }

      if (['INPUT', 'TEXTAREA'].includes((e.target as HTMLElement).tagName) || (e.target as HTMLElement).isContentEditable) {
        if (e.key === 'Escape') {
          (e.target as HTMLElement).blur()
          setSidebarOpen(false)
          setChatPanelOpen(false)
        }
        return
      }

      if (e.key === 'Escape') {
        setSidebarOpen(false)
        setChatPanelOpen(false)
      } else if (e.key === 'n' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        handleNewChat()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [setSidebarOpen, setChatPanelOpen])

  useEffect(() => {
    get<any>('/api/settings')
      .then(s => {
        setAgentName(s.agent?.name || 'Odigos')
      })
      .catch(() => {})
  }, [])

  const loadConversations = useCallback(() => {
    get<{ conversations: Conversation[] }>('/api/conversations?limit=50')
      .then((data) => {
        setConversations(data.conversations.map(c => ({
          ...c,
          title: pendingTitles.current[c.id] || c.title
        })))
      })
      .catch(() => {})
  }, [])

  const loadMessages = useCallback((cid: string) => {
    get<{ messages: ChatMessage[] }>(`/api/conversations/${cid}/messages`)
      .then((data) => setMessages(data.messages))
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (activeId) loadMessages(activeId)
    else setMessages([])
  }, [activeId, loadMessages])

  // Persistent WebSocket
  useEffect(() => {
    const socket = new ChatSocket(
      (msg) => {
        if (msg.type === 'notification') {
          const body = (msg.body || msg.message || '') as string
          const title = msg.title as string | undefined
          const label = title ? `${title}: ${body}` : body
          const priority = (msg.priority || 'info') as string
          if (title?.toLowerCase().includes('email')) setHasNewEmail(true)
          if (priority === 'urgent') toast.error(label)
          else if (priority === 'warning') toast.warning(label)
          else toast.info(label)
        }
        if (msg.type === 'status') setStatus(msg.text as string)
        if (msg.type === 'chat_chunk') {
          if (msg.conversation_id && activeIdRef.current && msg.conversation_id !== activeIdRef.current) return 
          setThinking(false)
          setStatus(null)
          setStreamingContent((prev) => prev + (msg.content as string))
        }
        if (msg.type === 'chat_response') {
          if (msg.conversation_id && activeIdRef.current && msg.conversation_id !== activeIdRef.current) return 
          setThinking(false)
          setStatus(null)
          setStreamingContent('')
          const content = msg.content as string
          setMessages((prev) => [...prev, {
            role: 'assistant',
            content,
            timestamp: new Date().toISOString(),
          }])
          if (shouldPlayTTS(content)) {
            playTTS(stripForTTS(content))
          }
          if (Array.isArray(msg.actions) && msg.actions.length > 0) {
            executeActions(msg.actions as UIAction[], navigateRef.current, {
              refresh: () => window.location.reload(),
              openChat: () => setChatPanelOpen(true),
              setTheme: (t) => setThemeRef.current(t),
            })
          }
        }
        if (msg.type === 'stream_end') { setThinking(false); setStatus(null) }
        if (msg.type === 'queue_update') {
          const queued = msg.queued as number
          setQueuedCount(queued)
          if (queued === 0) setThinking(false)
        }
        if (msg.type === 'message_queued') setStatus(`Queued (${msg.queued as number} pending)`)
        if (msg.type === 'queue_full') toast.warning('Message queue is full. Please wait.')
        if (msg.type === 'suggested_actions' && msg.actions) setSuggestedActions(msg.actions as string[])
        if (msg.type === 'title_updated' && msg.conversation_id && msg.title) {
          const cid = msg.conversation_id as string
          const title = msg.title as string
          pendingTitles.current[cid] = title
          setConversations((prev) => prev.map((c) => (c.id === cid ? { ...c, title } : c)))
        }
        if (msg.type === 'feed_update') toast.info(`New feed items from ${msg.source || 'RSS feed'}`, { duration: 4000 })
        if (msg.type === 'email_received') {
          setHasNewEmail(true)
          toast.info(`New email: ${msg.subject || 'New message'}`, { duration: 5000 })
        }
        if (msg.type === 'task_completed') toast.success(`Completed: ${msg.task || 'Background task'}`, { duration: 3000 })
      },
      (isConnected) => {
        setConnected(isConnected)
        if (!isConnected) toast.error('Disconnected from server', { duration: 5000 })
      },
    )
    socket.connect()
    socketRef.current = socket

    // Request push notification permission and subscribe
    if (Notification.permission === 'default') {
      Notification.requestPermission().then((perm) => {
        if (perm === 'granted') subscribeToPush()
      })
    } else if (Notification.permission === 'granted') {
      subscribeToPush()
    }

    return () => socket.disconnect()
  }, [loadConversations, playTTS])

  useEffect(() => { loadConversations() }, [loadConversations])

  useEffect(() => {
    const cid = searchParams.get('c')
    if (cid) setActiveId(cid)
  }, [searchParams])

  useEffect(() => { if (editingId) editInputRef.current?.focus() }, [editingId])

  function handleNewChat() {
    setActiveId(null)
    setSidebarOpen(false)
    setSearchQuery('')
    navigate('/')
  }

  function handleSelectConversation(id: string) {
    setActiveId(id)
    setSidebarOpen(false)
    setSearchQuery('')
    navigate(`/?c=${id}`)
  }

  const handleSelectImage = useCallback((id: string) => {
    setActiveArtifactId(id)
    setArtifactPanelOpen(true)
  }, [])

  const startRename = useCallback((c: Conversation | null) => {
    if (!c) {
      setEditingId(null)
      setEditTitle('')
      return
    }
    setEditingId(c.id)
    setEditTitle(c.title || c.id.slice(0, 8))
  }, [])

  const confirmRename = useCallback(async () => {
    if (!editingId || !editTitle.trim()) { setEditingId(null); return }
    try {
      await patch(`/api/conversations/${editingId}`, { title: editTitle.trim() })
      setConversations((prev) => prev.map((c) => (c.id === editingId ? { ...c, title: editTitle.trim() } : c)))
    } catch { toast.error('Failed to rename conversation') }
    setEditingId(null)
  }, [editingId, editTitle])

  async function handleDelete(id: string) {
    try {
      await del(`/api/conversations/${id}`)
      setConversations((prev) => prev.filter((c) => c.id !== id))
      if (activeId === id) { setActiveId(null); navigate('/') }
      toast.success('Conversation deleted')
    } catch { toast.error('Failed to delete conversation') }
  }

  const handleExport = useCallback((id: string, format: 'markdown' | 'json') => {
    const url = `/api/conversations/${id}/export?format=${format}`
    fetch(url).then(res => res.blob()).then(blob => {
      const ext = format === 'json' ? 'json' : 'md'
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = `${id}.${ext}`
      a.click()
      URL.revokeObjectURL(a.href)
      toast.success('Conversation exported')
    }).catch(() => toast.error('Failed to export conversation'))
  }, [])

  const displayTitle = useCallback((c: Conversation): string => {
    if (c.title) return c.title
    const raw = c.last_message_at || c.started_at
    if (!raw) return 'New chat'
    const date = new Date(raw + 'Z')
    return `Chat ${date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}`
  }, [])

  const isSettings = location.pathname.startsWith('/settings')
  const isNotebook = location.pathname.startsWith('/notebooks')
  const isKanban = location.pathname.startsWith('/kanban')
  const isImages = location.pathname.startsWith('/images')
  const isChat = !isSettings && !isNotebook && !isKanban && !isImages
  const currentTab = location.pathname.split('/')[2] || 'general'

  const filteredConversations = conversations.filter(c => 
    !searchQuery || displayTitle(c).toLowerCase().includes(searchQuery.toLowerCase())
  )

  useEffect(() => {
    if (isSettings) {
      setSidebarOpen(true)
      setCollapsed(false)
    }
  }, [isSettings])

  useEffect(() => {
    if (isNotebook && notebooks.length === 0) {
      get<{ notebooks: any[] }>('/api/notebooks').then(d => setNotebooks(d.notebooks))
    }
    if (isKanban && boards.length === 0) {
      get<{ boards: any[] }>('/api/kanban/boards').then(d => setBoards(d.boards))
    }
    if (isImages && images.length === 0) {
      get<{ artifacts: Artifact[] }>('/api/artifacts').then(d => {
        setImages((d.artifacts || []).filter(a => a.content_type?.startsWith('image/')).slice(0, 10))
      })
    }
  }, [isNotebook, isKanban, isImages, notebooks.length, boards.length, images.length])

  const handleCreateNotebook = useCallback(async () => {
    try {
      const res = await post<{ id: string }>('/api/notebooks', { title: 'Untitled Note' })
      setNotebooks(prev => [{ id: res.id, title: 'Untitled Note', updated_at: new Date().toISOString() }, ...prev])
      navigate(`/notebooks/${res.id}`)
    } catch { toast.error('Failed to create notebook') }
  }, [navigate])

  const handleCreateBoard = useCallback(async () => {
    try {
      const res = await post<{ id: string }>('/api/kanban/boards', { title: 'Untitled Board' })
      setBoards(prev => [{ id: res.id, title: 'Untitled Board', updated_at: new Date().toISOString() }, ...prev])
      navigate(`/kanban/${res.id}`)
    } catch { toast.error('Failed to create board') }
  }, [navigate])

  return (
    <TooltipProvider>
      <div className="flex h-[100dvh] bg-background text-foreground relative overflow-hidden">
        <QuickSwitcher open={switcherOpen} onOpenChange={setSwitcherOpen} />
        
        {/* Mobile top bar */}
        {!focusMode && (
          <div className="flex items-center gap-2 p-3 pt-safe border-b border-border/40 lg:hidden fixed top-0 left-0 right-0 z-20 bg-background">
            <Button variant="ghost" size="icon" aria-label="Toggle mobile menu" className="h-11 w-11" onClick={() => setSidebarOpen(true)}>
              <Menu className="h-5 w-5" />
            </Button>
            <button onClick={() => navigate('/')} className="text-sm font-semibold hover:text-muted-foreground transition-colors truncate max-w-[150px]">
              {isSettings && isMobile ? (
                <div className="flex items-center gap-2">
                  <ArrowLeft className="h-4 w-4" onClick={(e) => { e.stopPropagation(); navigate('/settings') }} />
                  <span>{SETTINGS_SECTIONS.find(s => s.id === currentTab)?.label || 'Settings'}</span>
                </div>
              ) : agentName}
            </button>
            <Button variant="ghost" size="icon" aria-label={isNotebook ? 'New Note' : isKanban ? 'New Board' : 'New Chat'} className="h-11 w-11 ml-auto" onClick={() => {
              if (isNotebook) { handleCreateNotebook(); toast.success('Note created') }
              else if (isKanban) { handleCreateBoard(); toast.success('Board created') }
              else if (isImages) { /* Upload handled in sidebar or page */ }
              else { handleNewChat(); toast.success('New chat') }
            }}>
              <Plus className="h-5 w-5" />
            </Button>
          </div>
        )}

        <AppSidebar 
          collapsed={collapsed} setCollapsed={setCollapsed} 
          sidebarOpen={sidebarOpen} setSidebarOpen={setSidebarOpen}
          isMobile={isMobile} searchQuery={searchQuery} setSearchQuery={setSearchQuery}
          isSettings={isSettings} isNotebook={isNotebook} isKanban={isKanban} isChat={isChat} isImages={isImages}
          currentTab={currentTab} agentName={agentName}
          notebooks={notebooks} boards={boards} images={images}
          filteredConversations={filteredConversations} activeId={activeId}
          handleNewChat={handleNewChat} handleCreateNotebook={handleCreateNotebook}
          handleCreateBoard={handleCreateBoard} handleSelectConversation={handleSelectConversation}
          handleSelectImage={handleSelectImage}
          startRename={startRename} editingId={editingId} editTitle={editTitle}
          setEditTitle={setEditTitle} confirmRename={confirmRename}
          handleExport={handleExport} handleDelete={handleDelete}
          displayTitle={displayTitle} navigate={navigate} location={location}
        />

        {sidebarOpen && <div className="fixed inset-0 z-30 bg-background/80 backdrop-blur-sm lg:hidden" onClick={() => setSidebarOpen(false)} />}

        <div className="flex-1 flex overflow-hidden relative">
          <main className={`flex-1 flex flex-col min-w-0 overflow-hidden pt-[52px] lg:pt-0 transition-all duration-300 ${artifactPanelOpen ? 'lg:max-w-[350px] border-r border-border/40' : ''}`}>
            <ErrorBoundary>
              {artifactPanelOpen ? (
                <ChatPanel activeConversationId={activeId} socketRef={socketRef} connected={connected} chatContext={chatContext} isSidePanel={false} />
              ) : (
                <Outlet context={{
                  activeId,
                  setActiveId,
                  activeConversationId: activeId,
                  refreshConversations: loadConversations,
                  socketRef, connected, hasNewEmail, setHasNewEmail, setChatPanelOpen,
                  artifactPanelOpen, setArtifactPanelOpen, activeArtifactId, setActiveArtifactId,
                  chatContext, setChatContext, isMobile, messages, setMessages,
                  streamingContent, setStreamingContent, thinking, setThinking, status, setStatus,
                  queuedCount, setQueuedCount, suggestedActions, setSuggestedActions,
                  playTTS, stopTTS, isTTSPlaying, focusMode, setFocusMode,
                  agentName,
                  setPageContextData: setChatContext,
                  sttAvailable: true,
                }} />
              )}
            </ErrorBoundary>
          </main>
          
          {chatPanelOpen && !artifactPanelOpen && (
            <aside className="fixed inset-0 z-50 lg:static lg:border-l lg:border-border/40 lg:w-[400px] lg:min-w-[400px] bg-background flex flex-col overflow-hidden animate-in slide-in-from-right duration-300 shadow-2xl">
              <ChatPanel activeConversationId={activeId} socketRef={socketRef} connected={connected} chatContext={chatContext} isSidePanel={true} onClose={() => setChatPanelOpen(false)} />
            </aside>
          )}

          {artifactPanelOpen && activeArtifactId && (
            <>
              {isMobile ? (
                <aside className="fixed inset-x-0 bottom-0 z-50 h-[85vh] bg-background border-t border-border/40 rounded-t-3xl shadow-2xl flex flex-col overflow-hidden animate-in slide-in-from-bottom duration-300 ease-out">
                  <div className="w-12 h-1 bg-muted rounded-full mx-auto my-3 shrink-0" />
                  <ArtifactPreview artifactId={activeArtifactId} onClose={() => setArtifactPanelOpen(false)} />
                </aside>
              ) : (
                <aside className="fixed inset-0 z-50 lg:static lg:flex-1 lg:min-w-0 bg-background flex flex-col overflow-hidden animate-in slide-in-from-right duration-300 shadow-inner">
                  <ArtifactPreview artifactId={activeArtifactId} onClose={() => setArtifactPanelOpen(false)} />
                </aside>
              )}
            </>
          )}
        </div>
      </div>
    </TooltipProvider>
  )
}
