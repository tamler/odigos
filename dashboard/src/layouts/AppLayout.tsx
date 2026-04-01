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
import { get, getBlob, patch, del, uploadFile } from '@/lib/api'
import { ChatSocket } from '@/lib/ws'
import { toast } from 'sonner'
import { executeActions, UIAction } from '@/lib/actions'
import { useTheme } from 'next-themes'
import { stripForTTS, shouldPlayTTS } from '@/lib/tts-filter'
import { useAudio } from '@/hooks/useAudio'
import { usePwaInstall } from '@/hooks/usePwaInstall'
import { useDriver } from '@/hooks/useDriver'
import { subscribeToPush } from '@/lib/push'
import { Artifact } from '@/components/ArtifactCard'
import { useChatStore } from '@/stores/chatStore'
import { useUIStore } from '@/stores/uiStore'
import { useConversationStore } from '@/stores/conversationStore'
import type { Conversation } from '@/stores/conversationStore'

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
  editingId, editTitle, setEditTitle,
  confirmRename, handleExport, handleDelete, displayTitle,
  startRename,
  handleNewChat, handleSelectConversation, handleSelectImage: _handleSelectImage,
  pwaInstallable, pwaInstall,
}: any) => {
  const collapsed = useUIStore(s => s.collapsed)
  const setCollapsed = useUIStore(s => s.setCollapsed)
  const sidebarOpen = useUIStore(s => s.sidebarOpen)
  const setSidebarOpen = useUIStore(s => s.setSidebarOpen)
  const isMobile = useUIStore(s => s.isMobile)
  const agentName = useUIStore(s => s.agentName)
  const searchQuery = useConversationStore(s => s.searchQuery)
  const setSearchQuery = useConversationStore(s => s.setSearchQuery)
  const notebooks = useConversationStore(s => s.notebooks)
  const boards = useConversationStore(s => s.boards)
  const images = useConversationStore(s => s.images)
  const filteredConversations = useConversationStore(s => s.filteredConversations)()
  const activeId = useChatStore(s => s.activeConversationId)
  const navigate = useNavigate()
  const location = useLocation()

  const isSettings = location.pathname.startsWith('/settings')
  const isNotebook = location.pathname.startsWith('/notebooks')
  const isKanban = location.pathname.startsWith('/kanban')
  const isImages = location.pathname.startsWith('/images')
  const isChat = !isSettings && !isNotebook && !isKanban && !isImages
  const currentTab = location.pathname.split('/')[2] || 'general'

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
      window.location.reload()
    } catch {
      toast.error('Upload failed')
    }
  }

  return (
    <aside className={`fixed inset-y-0 left-0 z-40 w-64 flex flex-col bg-background transition-all duration-200 ease-in-out ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'} lg:static lg:translate-x-0 ${collapsed && !isSettings ? 'lg:w-14' : 'lg:w-64'}`}>
      <div className="flex flex-col gap-2 p-3 mb-2 shrink-0">
        <div className="flex items-center gap-1 mb-2 px-1 min-h-[32px]">
          <Button variant="ghost" size="icon" aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"} onClick={() => isMobile ? setSidebarOpen(false) : setCollapsed(!collapsed)} className="shrink-0 h-8 w-8">
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
        <div className="px-3 pb-2 pt-1 mb-2 relative group shrink-0">
          <Input placeholder="Search..." value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} className="h-8 text-xs bg-muted/40 focus-visible:ring-1 border-none rounded-lg pr-8" />
          <kbd className="absolute right-5 top-1/2 -translate-y-1/2 pointer-events-none hidden group-focus-within:inline-flex h-4 select-none items-center gap-1 rounded border bg-muted px-1 font-mono text-[8px] font-medium text-muted-foreground opacity-100">⌘K</kbd>
        </div>
      )}

      {!collapsed && (
        <ScrollArea className="flex-1 min-h-0 px-3">
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
              <div className="px-3 py-4 text-center text-xs text-muted-foreground">
                {images.length} images
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
                    {editingId !== c.id && (
                      <div className={`absolute right-1 top-1/2 -translate-y-1/2 ${activeId === c.id ? 'opacity-100' : 'lg:opacity-0 lg:group-hover:opacity-100'}`}>
                        <DropdownMenu>
                          <DropdownMenuTrigger><Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground hover:text-foreground"><MoreHorizontal className="h-3.5 w-3.5" /></Button></DropdownMenuTrigger>
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

      <div className="p-3 mt-auto border-t border-border/10 space-y-1">
        {pwaInstallable && !collapsed && (
          <button
            onClick={pwaInstall}
            className="flex items-center gap-3 w-full p-2.5 rounded-xl text-muted-foreground hover:bg-muted transition-all"
            title="Install App"
          >
            <Download className="h-4 w-4 shrink-0" />
            <span className="text-sm font-medium">Install App</span>
          </button>
        )}
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
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editTitle, setEditTitle] = useState('')
  const [chatContext, setChatContext] = useState<Record<string, string> | undefined>(undefined)
  const editInputRef = useRef<HTMLInputElement>(null)
  const socketRef = useRef<ChatSocket | null>(null)
  const navigate = useNavigate()
  const navigateRef = useRef(navigate)
  navigateRef.current = navigate
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const { setTheme } = useTheme()
  const setThemeRef = useRef(setTheme)
  setThemeRef.current = setTheme
  const pendingTitles = useRef<Record<string, string>>({})

  // Zustand store access via getState() for non-rendering usage
  const activeConversationId = useChatStore(s => s.activeConversationId)
  const setActiveConversationId = useChatStore(s => s.setActiveConversationId)
  const sidebarOpen = useUIStore(s => s.sidebarOpen)
  const setSidebarOpen = useUIStore(s => s.setSidebarOpen)
  const isMobile = useUIStore(s => s.isMobile)
  const focusMode = useUIStore(s => s.focusMode)
  const switcherOpen = useUIStore(s => s.switcherOpen)
  const setSwitcherOpen = useUIStore(s => s.setSwitcherOpen)
  const chatPanelOpen = useUIStore(s => s.chatPanelOpen)
  const setChatPanelOpen = useUIStore(s => s.setChatPanelOpen)
  const artifactPanelOpen = useUIStore(s => s.artifactPanelOpen)
  const setArtifactPanelOpen = useUIStore(s => s.setArtifactPanelOpen)
  const activeArtifactId = useUIStore(s => s.activeArtifactId)
  const connected = useUIStore(s => s.connected)

  const { play: playTTS, stop: stopTTS, playing: isTTSPlaying } = useAudio()
  const { installable: pwaInstallable, install: pwaInstall } = usePwaInstall()
  const { highlight: driverHighlight } = useDriver()

  const activeIdRef = useRef(activeConversationId)

  useEffect(() => {
    activeIdRef.current = activeConversationId
  }, [activeConversationId])

  useEffect(() => {
    const handleResize = () => useUIStore.getState().setIsMobile(window.innerWidth < 1024)
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        useUIStore.getState().setSwitcherOpen(true)
        return
      }

      if (['INPUT', 'TEXTAREA'].includes((e.target as HTMLElement).tagName) || (e.target as HTMLElement).isContentEditable) {
        if (e.key === 'Escape') {
          (e.target as HTMLElement).blur()
          useUIStore.getState().setSidebarOpen(false)
          useUIStore.getState().setChatPanelOpen(false)
        }
        return
      }

      if (e.key === 'Escape') {
        useUIStore.getState().setSidebarOpen(false)
        useUIStore.getState().setChatPanelOpen(false)
      } else if (e.key === 'n' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        handleNewChat()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

  useEffect(() => {
    get<any>('/api/settings')
      .then(s => {
        useUIStore.getState().setAgentName(s.agent?.name || 'Odigos')
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (isMobile) useUIStore.getState().setSidebarOpen(false)
  }, [location.pathname, isMobile])

  const loadConversations = useCallback(() => {
    useConversationStore.getState().refreshConversations(pendingTitles.current)
  }, [])

  const loadMessages = useCallback((cid: string, limit = 50, offset = 0) => {
    get<{ messages: ChatMessage[] }>(`/api/conversations/${cid}/messages?limit=${limit}&offset=${offset}`)
      .then((data) => {
        if (offset > 0) {
          useChatStore.getState().setMessages((prev) => [...data.messages, ...prev])
        } else {
          useChatStore.getState().setMessages(data.messages)
        }
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (activeConversationId) loadMessages(activeConversationId)
    else useChatStore.getState().setMessages([])
  }, [activeConversationId, loadMessages])

  // Persistent WebSocket
  useEffect(() => {
    const socket = new ChatSocket(
      (msg) => {
        const chat = useChatStore.getState()
        const ui = useUIStore.getState()

        if (msg.type === 'notification') {
          const body = (msg.body || msg.message || '') as string
          const title = msg.title as string | undefined
          const label = title ? `${title}: ${body}` : body
          const priority = (msg.priority || 'info') as string
          if (title?.toLowerCase().includes('email')) ui.setHasNewEmail(true)
          if (priority === 'urgent') toast.error(label)
          else if (priority === 'warning') toast.warning(label)
          else toast.info(label)
        }
        if (msg.type === 'status') chat.setStatus(msg.text as string)
        if (msg.type === 'chat_chunk') {
          if (msg.conversation_id && activeIdRef.current && msg.conversation_id !== activeIdRef.current) return
          chat.setThinking(false)
          chat.setStatus(null)
          chat.setStreamingContent((prev) => prev + (msg.content as string))
        }
        if (msg.type === 'chat_response') {
          if (msg.conversation_id && activeIdRef.current && msg.conversation_id !== activeIdRef.current) return
          if (!activeIdRef.current && msg.conversation_id) {
            const newId = msg.conversation_id as string
            const chatId = newId.includes(':') ? newId.split(':')[1] : newId
            chat.setActiveConversationId(chatId)
          }
          chat.setThinking(false)
          chat.setStatus(null)
          chat.setStreamingContent('')
          const content = msg.content as string
          chat.setMessages((prev) => [...prev, {
            role: 'assistant',
            content,
            timestamp: new Date().toISOString(),
          }])
          if (ui.focusMode && shouldPlayTTS(content)) {
            playTTS(stripForTTS(content))
          }
          if (Array.isArray(msg.actions) && msg.actions.length > 0) {
            executeActions(msg.actions as UIAction[], navigateRef.current, {
              refresh: () => window.location.reload(),
              openChat: () => ui.setChatPanelOpen(true),
              setTheme: (t) => setThemeRef.current(t),
              stopTTS,
              highlight: driverHighlight,
            })
          }
        }
        if (msg.type === 'stream_end') { chat.setThinking(false); chat.setStatus(null) }
        if (msg.type === 'queue_update') {
          const queued = msg.queued as number
          chat.setQueuedCount(queued)
          if (queued === 0) chat.setThinking(false)
        }
        if (msg.type === 'message_queued') chat.setStatus(`Queued (${msg.queued as number} pending)`)
        if (msg.type === 'queue_full') toast.warning('Message queue is full. Please wait.')
        if (msg.type === 'suggested_actions' && msg.actions) chat.setSuggestedActions(msg.actions as string[])
        if (msg.type === 'title_updated' && msg.conversation_id && msg.title) {
          const cid = msg.conversation_id as string
          const title = msg.title as string
          pendingTitles.current[cid] = title
          useConversationStore.getState().setConversations((prev) => prev.map((c) => (c.id === cid ? { ...c, title } : c)))
        }
        if (msg.type === 'feed_update') toast.info(`New feed items from ${msg.source || 'RSS feed'}`, { duration: 4000 })
        if (msg.type === 'email_received') {
          ui.setHasNewEmail(true)
          toast.info(`New email: ${msg.subject || 'New message'}`, { duration: 5000 })
        }
        if (msg.type === 'task_completed') toast.success(`Completed: ${msg.task || 'Background task'}`, { duration: 3000 })
      },
      (isConnected) => {
        const wasConnected = useUIStore.getState().connected
        useUIStore.getState().setConnected(isConnected)
        if (isConnected && !wasConnected) toast.dismiss()
        if (!isConnected && wasConnected) toast('Reconnecting...', { duration: 3000 })
      },
    )
    socket.connect()
    socketRef.current = socket

    if (typeof Notification !== 'undefined') {
      if (Notification.permission === 'default') {
        Notification.requestPermission().then((perm) => {
          if (perm === 'granted') subscribeToPush()
        }).catch(() => {})
      } else if (Notification.permission === 'granted') {
        subscribeToPush()
      }
    }

    return () => socket.disconnect()
  }, [playTTS])

  useEffect(() => { loadConversations() }, [loadConversations])

  useEffect(() => {
    const cid = searchParams.get('c')
    if (cid) setActiveConversationId(cid)
  }, [searchParams, setActiveConversationId])

  useEffect(() => { if (editingId) editInputRef.current?.focus() }, [editingId])

  const handleNewChat = useCallback(() => {
    useChatStore.getState().setActiveConversationId(null)
    useChatStore.getState().setMessages([])
    useChatStore.getState().setStreamingContent('')
    useChatStore.getState().setThinking(false)
    useChatStore.getState().setStatus(null)
    useChatStore.getState().setSuggestedActions([])
    useUIStore.getState().setSidebarOpen(false)
    useConversationStore.getState().setSearchQuery('')
    navigate('/')
  }, [navigate])

  const handleSelectConversation = useCallback((id: string) => {
    useChatStore.getState().setActiveConversationId(id)
    useUIStore.getState().setSidebarOpen(false)
    useConversationStore.getState().setSearchQuery('')
    navigate(`/?c=${id}`)
  }, [navigate])

  const handleSelectImage = useCallback((id: string) => {
    useUIStore.getState().setActiveArtifactId(id)
    useUIStore.getState().setArtifactPanelOpen(true)
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
      useConversationStore.getState().setConversations((prev) => prev.map((c) => (c.id === editingId ? { ...c, title: editTitle.trim() } : c)))
    } catch { toast.error('Failed to rename conversation') }
    setEditingId(null)
  }, [editingId, editTitle])

  const handleDelete = useCallback(async (id: string) => {
    try {
      await del(`/api/conversations/${id}`)
      useConversationStore.getState().setConversations((prev) => prev.filter((c) => c.id !== id))
      if (activeConversationId === id) { setActiveConversationId(null); navigate('/') }
      toast.success('Conversation deleted')
    } catch { toast.error('Failed to delete conversation') }
  }, [activeConversationId, navigate, setActiveConversationId])

  const handleExport = useCallback((id: string, format: 'markdown' | 'json') => {
    const url = `/api/conversations/${id}/export?format=${format}`
    getBlob(url).then(blob => {
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

  useEffect(() => {
    if (isSettings && !isMobile) {
      useUIStore.getState().setSidebarOpen(true)
      useUIStore.getState().setCollapsed(false)
    }
  }, [isSettings, isMobile])

  useEffect(() => {
    if (isNotebook && useConversationStore.getState().notebooks.length === 0) {
      get<{ notebooks: any[] }>('/api/notebooks').then(d => useConversationStore.getState().setNotebooks(d.notebooks))
    }
    if (isKanban && useConversationStore.getState().boards.length === 0) {
      get<{ boards: any[] }>('/api/kanban/boards').then(d => useConversationStore.getState().setBoards(d.boards))
    }
    if (isImages && useConversationStore.getState().images.length === 0) {
      get<{ artifacts: Artifact[] }>('/api/artifacts').then(d => {
        useConversationStore.getState().setImages((d.artifacts || []).filter(a => a.content_type?.startsWith('image/')).slice(0, 10))
      })
    }
  }, [isNotebook, isKanban, isImages])

  return (
    <TooltipProvider>
      <div className="flex h-[100dvh] bg-background text-foreground relative overflow-hidden">
        <QuickSwitcher open={switcherOpen} onOpenChange={setSwitcherOpen} />

        {!focusMode && !sidebarOpen && (
          <Button
            variant="ghost"
            size="icon"
            aria-label={isSettings ? "Back to chat" : "Open menu"}
            className="lg:hidden fixed top-3 left-3 z-20 h-9 w-9 text-muted-foreground/50 hover:text-foreground"
            style={{ paddingTop: 'env(safe-area-inset-top, 0px)' }}
            onClick={() => isSettings ? navigate('/') : setSidebarOpen(true)}
          >
            {isSettings ? <MessageCircle className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
          </Button>
        )}

        <AppSidebar
          editingId={editingId} editTitle={editTitle}
          setEditTitle={setEditTitle} confirmRename={confirmRename}
          handleExport={handleExport} handleDelete={handleDelete}
          displayTitle={displayTitle} startRename={startRename}
          handleNewChat={handleNewChat} handleSelectConversation={handleSelectConversation}
          handleSelectImage={handleSelectImage}
          pwaInstallable={pwaInstallable} pwaInstall={pwaInstall}
        />

        {sidebarOpen && <div className="fixed inset-0 z-30 bg-background lg:hidden" onClick={() => setSidebarOpen(false)} onTouchMove={(e) => e.preventDefault()} />}

        <div className="flex-1 flex overflow-hidden relative">
          <main className={`flex-1 flex flex-col min-w-0 overflow-hidden lg:pt-0 transition-all duration-300 ${artifactPanelOpen ? 'lg:max-w-[350px] border-r border-border/40' : ''}`}>
            <ErrorBoundary>
              {artifactPanelOpen ? (
                <ChatPanel activeConversationId={activeConversationId} socketRef={socketRef} connected={connected} chatContext={chatContext} isSidePanel={false} />
              ) : (
                <Outlet context={{
                  socketRef,
                  playTTS, stopTTS, isTTSPlaying,
                  highlight: driverHighlight,
                  chatContext, setChatContext,
                  setPageContextData: setChatContext,
                }} />
              )}
            </ErrorBoundary>
          </main>

          {chatPanelOpen && !artifactPanelOpen && (
            <aside className="fixed inset-0 z-50 lg:static lg:border-l lg:border-border/40 lg:w-[400px] lg:min-w-[400px] bg-background flex flex-col overflow-hidden animate-in slide-in-from-right duration-300 shadow-2xl">
              <ChatPanel activeConversationId={activeConversationId} socketRef={socketRef} connected={connected} chatContext={chatContext} isSidePanel={true} onClose={() => setChatPanelOpen(false)} />
            </aside>
          )}

          {artifactPanelOpen && activeArtifactId && (
            <>
              {isMobile ? (
                <aside className="fixed inset-0 z-50 bg-background flex flex-col overflow-hidden animate-in slide-in-from-bottom duration-300 ease-out">
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
