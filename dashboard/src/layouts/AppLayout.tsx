import { useState, useEffect, useCallback, useRef } from 'react'
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
  Eye
} from 'lucide-react'
import { ChatPanel } from '@/components/ChatPanel'
import { FloatingBubble } from '@/components/FloatingBubble'
import { ArtifactPreview } from '@/components/ArtifactPreview'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { get, patch, del } from '@/lib/api'
import { ChatSocket } from '@/lib/ws'
import { toast } from 'sonner'
import { executeActions, UIAction } from '@/lib/actions'
import { PageContext } from '@/hooks/usePageContext'
import { useTheme } from 'next-themes'
import { stripForTTS, shouldPlayTTS } from '@/lib/tts-filter'

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

export default function AppLayout() {
  const [collapsed, setCollapsed] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [isMobile, setIsMobile] = useState(typeof window !== 'undefined' ? window.innerWidth < 1024 : false)
  const [searchQuery, setSearchQuery] = useState('')
  const [conversations, setConversations] = useState<Conversation[]>([])
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
  const [pageContextData, setPageContextData] = useState<Partial<PageContext>>({})
  const [assistantConfig, setAssistantConfig] = useState<AssistantConfig>({
    enabled: false,
    show_transcript: true,
    text_input: true,
    voice_input: true,
    auto_read: false,
    position: 'bottom-right'
  })
  const [chatContext, setChatContext] = useState<Record<string, string> | undefined>(undefined)
  const editInputRef = useRef<HTMLInputElement>(null)
  const socketRef = useRef<ChatSocket | null>(null)
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const [agentName, setAgentName] = useState('Odigos')
  const { setTheme } = useTheme()
  const currentAudioRef = useRef<HTMLAudioElement | null>(null)
  const pendingTitles = useRef<Record<string, string>>({})

  const [isTTSPlaying, setIsTTSPlaying] = useState(false)

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

  // Keyboard shortcuts (G14)
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
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
      } else if (e.key === 'k' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        const textarea = document.querySelector('textarea')
        if (textarea) textarea.focus()
      } else if (e.key === 'n' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        handleNewChat()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    // We intentionally don't add handleNewChat to the dep array if it's not useCallback, 
    // but React might warn. We can ignore or wrap handleNewChat in useCallback.
    // For now we'll just omit it from the deps array.
  }, [setSidebarOpen, setChatPanelOpen])



  useEffect(() => {
    get<any>('/api/settings')
      .then(s => {
        setAgentName(s.agent?.name || 'Odigos')
        if (s.assistant) setAssistantConfig(s.assistant)
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

  // Persistent WebSocket — lives at layout level, survives page navigation
  useEffect(() => {
    const socket = new ChatSocket(
      (msg) => {
        // Global notification handler -- toasts show on any page
        if (msg.type === 'notification') {
          const body = (msg.body || msg.message || '') as string
          const title = msg.title as string | undefined
          const label = title ? `${title}: ${body}` : body
          const priority = (msg.priority || 'info') as string

          if (title?.toLowerCase().includes('email')) {
            setHasNewEmail(true)
          }

          if (priority === 'urgent') {
            toast.error(label)
          } else if (priority === 'warning') {
            toast.warning(label)
          } else {
            toast.info(label)
          }
        }
        if (msg.type === 'status') {
          setStatus(msg.text as string)
        }
        if (msg.type === 'chat_chunk') {
          if (msg.conversation_id && activeId && msg.conversation_id !== activeId) {
            return 
          }
          setThinking(false)
          setStatus(null)
          setStreamingContent((prev) => prev + (msg.content as string))
        }
        if (msg.type === 'chat_response') {
          if (msg.conversation_id && activeId && msg.conversation_id !== activeId) {
            return 
          }
          setThinking(false)
          setStatus(null)
          setStreamingContent('')
          const content = msg.content as string
          setMessages((prev) => [...prev, {
            role: 'assistant',
            content,
            timestamp: new Date().toISOString(),
          }])

          // Auto-read if enabled (G-V4)
          if (assistantConfig.auto_read && shouldPlayTTS(content)) {
            playTTS(stripForTTS(content))
          }

          // Handle UI Actions (G-B4)
          if (Array.isArray(msg.actions) && msg.actions.length > 0) {
            executeActions(msg.actions as UIAction[], navigate, {
              refresh: () => window.location.reload(),
              openChat: () => setChatPanelOpen(true),
              setTheme: (t) => setTheme(t),
            })
          }
        }
        if (msg.type === 'stream_end') {
          setThinking(false)
          setStatus(null)
        }
        if (msg.type === 'queue_update') {
          const queued = msg.queued as number
          setQueuedCount(queued)
          if (queued === 0) setThinking(false)
        }
        if (msg.type === 'message_queued') {
          setStatus(`Queued (${msg.queued as number} pending)`)
        }
        if (msg.type === 'queue_full') {
          toast.warning('Message queue is full. Please wait.')
        }
        if (msg.type === 'suggested_actions' && msg.actions) {
          setSuggestedActions(msg.actions as string[])
        }
        if (msg.type === 'title_updated' && msg.conversation_id && msg.title) {
          const cid = msg.conversation_id as string
          const title = msg.title as string
          pendingTitles.current[cid] = title
          setConversations((prev) =>
            prev.map((c) => (c.id === cid ? { ...c, title } : c))
          )
        }
        if (msg.type === 'feed_update') {
          toast.info(`New feed items from ${msg.source || 'RSS feed'}`, { duration: 4000 })
        }
        if (msg.type === 'email_received') {
          setHasNewEmail(true)
          toast.info(`New email: ${msg.subject || 'New message'}`, { duration: 5000 })
        }
        if (msg.type === 'task_completed') {
          toast.success(`Completed: ${msg.task || 'Background task'}`, { duration: 3000 })
        }
      },
      (isConnected) => {
        setConnected(isConnected)
        if (!isConnected) {
          toast.error('Disconnected from server', { duration: 5000 })
        }
      },
    )
    socket.connect()
    socketRef.current = socket
    return () => socket.disconnect()
  }, [loadConversations])

  useEffect(() => {
    loadConversations()
  }, [loadConversations])

  useEffect(() => {
    const cid = searchParams.get('c')
    if (cid) setActiveId(cid)
  }, [searchParams])

  useEffect(() => {
    if (editingId) editInputRef.current?.focus()
  }, [editingId])

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

  function startRename(c: Conversation) {
    setEditingId(c.id)
    setEditTitle(c.title || c.id.slice(0, 8))
  }

  async function confirmRename() {
    if (!editingId || !editTitle.trim()) {
      setEditingId(null)
      return
    }
    try {
      await patch(`/api/conversations/${editingId}`, { title: editTitle.trim() })
      setConversations((prev) =>
        prev.map((c) => (c.id === editingId ? { ...c, title: editTitle.trim() } : c))
      )
    } catch {
      toast.error('Failed to rename conversation')
    }
    setEditingId(null)
  }

  async function handleDelete(id: string) {
    try {
      await del(`/api/conversations/${id}`)
      setConversations((prev) => prev.filter((c) => c.id !== id))
      if (activeId === id) {
        setActiveId(null)
        navigate('/')
      }
      toast.success('Conversation deleted')
    } catch {
      toast.error('Failed to delete conversation')
    }
  }

  const handleExport = (id: string, format: 'markdown' | 'json') => {
    const url = `/api/conversations/${id}/export?format=${format}`
    fetch(url)
      .then((res) => {
        if (!res.ok) throw new Error('Export failed')
        return res.blob()
      })
      .then((blob) => {
        const ext = format === 'json' ? 'json' : 'md'
        const a = document.createElement('a')
        a.href = URL.createObjectURL(blob)
        a.download = `${id}.${ext}`
        a.click()
        URL.revokeObjectURL(a.href)
        toast.success('Conversation exported')
      })
      .catch(() => toast.error('Failed to export conversation'))
  }

  const handleBubbleSend = useCallback((content: string, context?: Record<string, any>) => {
    if (!content.trim()) return
    setMessages((prev) => [...prev, {
      role: 'user',
      content,
      timestamp: new Date().toISOString(),
    }])
    setThinking(true)
    socketRef.current?.send('chat', {
      content,
      conversation_id: activeId || undefined,
      context: { ...context, ...chatContext },
    })
  }, [activeId, chatContext])

  function displayTitle(c: Conversation): string {
    if (c.title) return c.title
    const raw = c.last_message_at || c.started_at
    if (!raw) return 'New chat'
    const date = new Date(raw + 'Z')
    const short = date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
    return `Chat ${short}`
  }

  const filteredConversations = conversations.filter(c => 
    !searchQuery || displayTitle(c).toLowerCase().includes(searchQuery.toLowerCase())
  )

  const isSettings = location.pathname.startsWith('/settings')
  const isChat = location.pathname === '/' || searchParams.has('c')
  const currentTab = location.pathname.split('/')[2] || 'general'

  return (
    <TooltipProvider>
      <div className="flex h-[100dvh] bg-background text-foreground">
        {/* Mobile top bar */}
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
          <Button variant="ghost" size="icon" aria-label="New chat" className="h-11 w-11 ml-auto" onClick={handleNewChat}>
            <Plus className="h-5 w-5" />
          </Button>
        </div>

        {/* Sidebar */}
        <aside className={`fixed inset-y-0 left-0 z-40 w-64 flex flex-col border-r border-border/40 bg-background transition-all duration-200 ease-in-out ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'} lg:static lg:translate-x-0 ${collapsed ? 'lg:w-14' : 'lg:w-64'}`}>
          {/* Top: Logo + New Chat */}
          <div className="flex flex-col gap-2 p-3 border-b border-border/40 mb-2">
            {!collapsed && (
              <button 
                onClick={() => navigate('/')} 
                className="text-lg font-bold tracking-tight px-3 py-1 hover:text-primary transition-colors text-left truncate"
              >
                {agentName}
              </button>
            )}
            <div className="flex items-center gap-2">
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button variant="ghost" size="icon" aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"} onClick={() => setCollapsed(!collapsed)} className="shrink-0 h-8 w-8">
                    {collapsed ? <PanelLeft className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="right">{collapsed ? 'Expand' : 'Collapse'}</TooltipContent>
              </Tooltip>
              {!collapsed && (
                <Button variant="secondary" size="sm" className="flex-1 justify-start gap-2 h-8" onClick={handleNewChat}>
                  <Plus className="h-4 w-4" /> New Chat
                </Button>
              )}
            </div>
          </div>

          {/* Conversation Search (Chat only) */}
          {!collapsed && !isSettings && (
            <div className="px-3 pb-2 pt-1 border-b border-border/40 mb-2">
              <Input 
                placeholder="Search conversations..." 
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="h-8 text-xs bg-muted/50 focus-visible:ring-1"
              />
            </div>
          )}

          {/* Sidebar Content (List) */}
          {!collapsed && (
            <ScrollArea className="flex-1 px-2">
              <div className="space-y-0.5 pb-4">
                {isSettings ? (
                  // Settings Sections
                  SETTINGS_SECTIONS.map((s) => (
                    <button
                      key={s.id}
                      onClick={() => { navigate(`/settings/${s.id}`); setSidebarOpen(false) }}
                      className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-md text-sm transition-colors ${
                        currentTab === s.id
                          ? 'bg-accent text-accent-foreground font-medium'
                          : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground'
                      }`}
                    >
                      <s.icon className="h-4 w-4 shrink-0" />
                      <span>{s.label}</span>
                    </button>
                  ))
                ) : (
                  // Conversation list
                  filteredConversations.length === 0 ? (
                    <div className="px-3 py-6 mt-4 text-center text-sm text-muted-foreground">
                      {searchQuery ? 'No matching conversations' : 'Start a new conversation'}
                    </div>
                  ) : (
                    filteredConversations.map((c) => (
                      <div key={c.id} className="group relative">
                      {editingId === c.id ? (
                        <div className="flex items-center gap-1 px-1 py-1">
                          <Input
                            ref={editInputRef}
                            value={editTitle}
                            onChange={(e) => setEditTitle(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') confirmRename()
                              if (e.key === 'Escape') setEditingId(null)
                            }}
                            className="h-7 text-sm"
                          />
                          <Button variant="ghost" size="icon" aria-label="Confirm rename" className="h-7 w-7 shrink-0" onClick={confirmRename}>
                            <Check className="h-3 w-3" />
                          </Button>
                          <Button variant="ghost" size="icon" aria-label="Cancel rename" className="h-7 w-7 shrink-0" onClick={() => setEditingId(null)}>
                            <X className="h-3 w-3" />
                          </Button>
                        </div>
                      ) : (
                        <button
                          onClick={() => handleSelectConversation(c.id)}
                          className={`w-full text-left px-3 py-2 min-h-[44px] rounded-md text-sm truncate transition-colors pr-8 ${
                            activeId === c.id
                              ? 'bg-accent text-accent-foreground'
                              : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground'
                          }`}
                        >
                          {displayTitle(c)}
                        </button>
                      )}
                      {editingId !== c.id && (
                        <div className="absolute right-1 top-1/2 -translate-y-1/2">
                          <DropdownMenu>
                            <DropdownMenuTrigger>
                              <Button variant="ghost" size="icon" aria-label="Conversation options" className="h-6 w-6">
                                <MoreHorizontal className="h-3 w-3" />
                              </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end" className="w-40">
                              <DropdownMenuItem onClick={() => startRename(c)}>
                                <Pencil className="h-3 w-3 mr-2" /> Rename
                              </DropdownMenuItem>
                              <DropdownMenuItem onClick={() => handleExport(c.id, 'markdown')}>
                                <Download className="h-3 w-3 mr-2" /> Export
                              </DropdownMenuItem>
                              <DropdownMenuSeparator />
                              <DropdownMenuItem
                                onClick={() => handleDelete(c.id)}
                                className="text-destructive focus:text-destructive"
                              >
                                <Trash2 className="h-3 w-3 mr-2" /> Delete
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        </div>
                      )}
                    </div>
                  )))
                )}
              </div>
            </ScrollArea>
          )}

          {/* Bottom: Settings / Chat Toggle (G-P7) */}
          <div className="p-3 mt-auto">
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  onClick={() => { setSidebarOpen(false); setSearchQuery(''); navigate(isSettings ? '/' : '/settings') }}
                  className={`flex items-center gap-2 p-2 rounded-md transition-colors text-muted-foreground hover:bg-accent/50 hover:text-foreground ${collapsed ? 'justify-center' : 'w-10'}`}
                  aria-label={isSettings ? "Chat" : "Settings"}
                >
                  {isSettings ? <MessageCircle className="h-4 w-4 shrink-0" /> : <Settings className="h-4 w-4 shrink-0" />}
                </button>
              </TooltipTrigger>
              <TooltipContent side="right">{isSettings ? "Chat" : "Settings"}</TooltipContent>
            </Tooltip>
          </div>
        </aside>

        {/* Backdrop for mobile sidebar */}
        {sidebarOpen && (
          <div
            className="fixed inset-0 z-30 bg-background/80 backdrop-blur-sm transition-all duration-200 lg:hidden"
            onClick={() => setSidebarOpen(false)}
          />
        )}

        {/* Main layout container */}
        <div className="flex-1 flex overflow-hidden relative">
          <main className={`flex-1 flex flex-col min-w-0 overflow-hidden pt-[52px] lg:pt-0 transition-all duration-300 ${artifactPanelOpen ? 'lg:max-w-[350px] border-r border-border/40' : ''}`}>
            <ErrorBoundary>
              {artifactPanelOpen ? (
                <ChatPanel
                  activeConversationId={activeId}
                  setActiveId={setActiveId}
                  refreshConversations={loadConversations}
                  socketRef={socketRef}
                  connected={connected}
                  chatContext={chatContext}
                  isSidePanel={false}
                />
              ) : (
                <Outlet context={{
                  activeConversationId: activeId,
                  setActiveId,
                  refreshConversations: loadConversations,
                  socketRef,
                  connected,
                  hasNewEmail,
                  setHasNewEmail,
                  setChatPanelOpen,
                  artifactPanelOpen,
                  setArtifactPanelOpen,
                  activeArtifactId,
                  setActiveArtifactId,
                  setChatContext,
                  isMobile,
                  setPageContextData,
                  messages,
                  setMessages,
                  streamingContent,
                  setStreamingContent,
                  thinking,
                  setThinking,
                  status,
                  setStatus,
                  queuedCount,
                  setQueuedCount,
                  suggestedActions,
                  setSuggestedActions,
                  playTTS,
                  stopTTS,
                  isTTSPlaying,
                }} />
              )}
            </ErrorBoundary>
          </main>
          
          {/* Contextual Chat Panel (Cowork mode) */}
          {chatPanelOpen && !artifactPanelOpen && (
            <aside className="fixed inset-0 z-50 lg:static lg:border-l lg:border-border/40 lg:w-[400px] lg:min-w-[400px] bg-background flex flex-col overflow-hidden animate-in slide-in-from-right duration-300">
              <ChatPanel
                activeConversationId={activeId}
                setActiveId={setActiveId}
                refreshConversations={loadConversations}
                socketRef={socketRef}
                connected={connected}
                chatContext={chatContext}
                isSidePanel={true}
                onClose={() => setChatPanelOpen(false)}
              />
            </aside>
          )}

          {/* Artifact Preview Panel / Bottom Sheet (G-P1) */}
          {artifactPanelOpen && activeArtifactId && (
            <>
              {isMobile ? (
                <>
                  <div 
                    className="fixed inset-0 z-40 bg-background/60 backdrop-blur-sm animate-in fade-in duration-300"
                    onClick={() => setArtifactPanelOpen(false)}
                  />
                  <aside className="fixed inset-x-0 bottom-0 z-50 h-[80vh] bg-background border-t border-border/40 rounded-t-3xl shadow-2xl flex flex-col overflow-hidden animate-in slide-in-from-bottom duration-300 ease-out">
                    <div className="w-12 h-1 bg-muted rounded-full mx-auto my-3 shrink-0" />
                    <ArtifactPreview 
                      artifactId={activeArtifactId} 
                      onClose={() => setArtifactPanelOpen(false)} 
                    />
                  </aside>
                </>
              ) : (
                <aside className="fixed inset-0 z-50 lg:static lg:flex-1 lg:min-w-0 bg-background flex flex-col overflow-hidden animate-in slide-in-from-right duration-300">
                  <ArtifactPreview 
                    artifactId={activeArtifactId} 
                    onClose={() => setArtifactPanelOpen(false)} 
                  />
                </aside>
              )}
            </>
          )}
        </div>

        {/* Floating Assistant Bubble (G-B1) */}
        {!isChat && !chatPanelOpen && assistantConfig.enabled && (
          <FloatingBubble
            socketRef={socketRef}
            connected={connected}
            activeConversationId={activeId}
            messages={messages}
            onSend={handleBubbleSend}
            pageContext={{ page: location.pathname.split('/')[1] || 'home', ...pageContextData }}
            assistantConfig={assistantConfig}
            agentName={agentName}
            ttsAvailable={assistantConfig.enabled} 
            sttAvailable={connected}
            playTTS={playTTS}
          />
        )}
      </div>
    </TooltipProvider>
  )
}
