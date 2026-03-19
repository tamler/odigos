import { useState, useEffect, useCallback, useRef } from 'react'
import { Outlet, useNavigate, useSearchParams, useLocation } from 'react-router-dom'
import { Settings, PanelLeftClose, PanelLeft, Plus, Pencil, Trash2, Check, X, Download, MoreHorizontal, Menu, MessageSquare, BookOpen, Columns3, BarChart3, Sun, Moon, Archive, Network } from 'lucide-react'
import { useTheme } from 'next-themes'
import { ChatPanel } from '@/components/ChatPanel'
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

interface Conversation {
  id: string
  started_at: string
  last_message_at: string | null
  title?: string | null
  message_count: number
}

export default function AppLayout() {
  const [collapsed, setCollapsed] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editTitle, setEditTitle] = useState('')
  const [connected, setConnected] = useState(false)
  const [chatPanelOpen, setChatPanelOpen] = useState(false)
  const [chatContext, setChatContext] = useState<Record<string, string> | undefined>(undefined)
  const editInputRef = useRef<HTMLInputElement>(null)
  const socketRef = useRef<ChatSocket | null>(null)
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const { theme, setTheme } = useTheme()

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



  const loadConversations = useCallback(() => {
    get<{ conversations: Conversation[] }>('/api/conversations?limit=50')
      .then((data) => setConversations(data.conversations))
      .catch(() => {})
  }, [])

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
          if (priority === 'urgent') {
            toast.error(label)
          } else if (priority === 'warning') {
            toast.warning(label)
          } else {
            toast.info(label)
          }
        }
        if (msg.type === 'title_updated' && msg.conversation_id && msg.title) {
          const cid = msg.conversation_id as string
          const title = msg.title as string
          setConversations((prev) =>
            prev.map((c) => (c.id === cid ? { ...c, title } : c))
          )
          loadConversations()
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

  function handleExport(id: string, format: 'markdown' | 'json') {
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

  const isSettingsPage = location.pathname === '/settings'

  return (
    <TooltipProvider>
      <div className="flex h-[100dvh] bg-background text-foreground">
        {/* Mobile top bar */}
        <div className="flex items-center gap-2 p-3 border-b border-border/40 lg:hidden fixed top-0 left-0 right-0 z-20 bg-background">
          <Button variant="ghost" size="icon" aria-label="Toggle mobile menu" className="h-11 w-11" onClick={() => setSidebarOpen(true)}>
            <Menu className="h-5 w-5" />
          </Button>
          <button onClick={() => navigate('/')} className="text-sm font-semibold hover:text-muted-foreground transition-colors">Odigos</button>
          <Button variant="ghost" size="icon" aria-label="New chat" className="h-11 w-11 ml-auto" onClick={handleNewChat}>
            <Plus className="h-5 w-5" />
          </Button>
        </div>

        {/* Sidebar */}
        <aside className={`fixed inset-y-0 left-0 z-40 w-64 flex flex-col border-r border-border/40 bg-background transition-all duration-200 ease-in-out ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'} lg:static lg:translate-x-0 ${collapsed ? 'lg:w-14' : 'lg:w-64'}`}>
          {/* Top: Toggle + New Chat */}
          <div className="flex items-center gap-2 p-3">
            <Tooltip>
              <TooltipTrigger>
                <Button variant="ghost" size="icon" aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"} onClick={() => setCollapsed(!collapsed)} className="shrink-0">
                  {collapsed ? <PanelLeft className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
                </Button>
              </TooltipTrigger>
              <TooltipContent side="right">{collapsed ? 'Expand' : 'Collapse'}</TooltipContent>
            </Tooltip>
            {!collapsed && (
              <Button variant="ghost" size="sm" className="flex-1 justify-start gap-2" onClick={handleNewChat}>
                <Plus className="h-4 w-4" /> New Chat
              </Button>
            )}
          </div>

          {/* Conversation Search */}
          {!collapsed && (
            <div className="px-3 pb-2 pt-1 border-b border-border/40 mb-2">
              <Input 
                placeholder="Search conversations..." 
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="h-8 text-xs bg-muted/50 focus-visible:ring-1"
              />
            </div>
          )}

          {/* Conversation list */}
          {!collapsed && (
            <ScrollArea className="flex-1 px-2">
              <div className="space-y-0.5 pb-4">
                {filteredConversations.length === 0 ? (
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
                )))}
              </div>
            </ScrollArea>
          )}

          {/* Bottom: Toggle between Chat and Settings */}
          <div className="p-3 mt-auto">
            <Tooltip>
              <TooltipTrigger>
                <button
                  onClick={() => { setSidebarOpen(false); navigate('/analytics') }}
                  className={`flex items-center gap-2 px-3 py-2 min-h-[44px] rounded-md text-sm transition-colors w-full ${
                    location.pathname.startsWith('/analytics')
                      ? 'bg-accent text-foreground'
                      : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground'
                  }`}
                >
                  <BarChart3 className="h-4 w-4 shrink-0" />{!collapsed && 'Analytics'}
                </button>
              </TooltipTrigger>
              {collapsed && <TooltipContent side="right">Analytics</TooltipContent>}
            </Tooltip>
            <Tooltip>
              <TooltipTrigger>
                <button
                  onClick={() => { setSidebarOpen(false); navigate('/kanban') }}
                  className={`flex items-center gap-2 px-3 py-2 min-h-[44px] rounded-md text-sm transition-colors w-full ${
                    location.pathname.startsWith('/kanban')
                      ? 'bg-accent text-foreground'
                      : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground'
                  }`}
                >
                  <Columns3 className="h-4 w-4 shrink-0" />{!collapsed && 'Kanban'}
                </button>
              </TooltipTrigger>
              {collapsed && <TooltipContent side="right">Kanban</TooltipContent>}
            </Tooltip>
            <Tooltip>
              <TooltipTrigger>
                <button
                  onClick={() => { setSidebarOpen(false); navigate('/notebooks') }}
                  className={`flex items-center gap-2 px-3 py-2 min-h-[44px] rounded-md text-sm transition-colors w-full ${
                    location.pathname.startsWith('/notebooks')
                      ? 'bg-accent text-foreground'
                      : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground'
                  }`}
                >
                  <BookOpen className="h-4 w-4 shrink-0" />{!collapsed && 'Notebooks'}
                </button>
              </TooltipTrigger>
              {collapsed && <TooltipContent side="right">Notebooks</TooltipContent>}
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  onClick={() => { setSidebarOpen(false); navigate('/artifacts') }}
                  className={`flex items-center gap-2 px-3 py-2 min-h-[44px] rounded-md text-sm transition-colors w-full ${
                    location.pathname.startsWith('/artifacts')
                      ? 'bg-accent text-foreground'
                      : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground'
                  }`}
                >
                  <Archive className="h-4 w-4 shrink-0" />{!collapsed && 'Artifacts'}
                </button>
              </TooltipTrigger>
              {collapsed && <TooltipContent side="right">Artifacts</TooltipContent>}
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  onClick={() => { setSidebarOpen(false); navigate('/mesh') }}
                  className={`flex items-center gap-2 px-3 py-2 min-h-[44px] rounded-md text-sm transition-colors w-full ${
                    location.pathname.startsWith('/mesh')
                      ? 'bg-accent text-foreground'
                      : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground'
                  }`}
                >
                  <Network className="h-4 w-4 shrink-0" />{!collapsed && 'Agent Mesh'}
                </button>
              </TooltipTrigger>
              {collapsed && <TooltipContent side="right">Agent Mesh</TooltipContent>}
            </Tooltip>
            <Tooltip>
              <TooltipTrigger>
                <button
                  onClick={() => { setSidebarOpen(false); setSearchQuery(''); navigate(isSettingsPage ? '/' : '/settings') }}
                  className="flex items-center gap-2 px-3 py-2 min-h-[44px] rounded-md text-sm transition-colors w-full text-muted-foreground hover:bg-accent/50 hover:text-foreground"
                >
                  {isSettingsPage ? (
                    <><MessageSquare className="h-4 w-4 shrink-0" />{!collapsed && 'Chat'}</>
                  ) : (
                    <><Settings className="h-4 w-4 shrink-0" />{!collapsed && 'Settings'}</>
                  )}
                </button>
              </TooltipTrigger>
              {collapsed && <TooltipContent side="right">{isSettingsPage ? 'Chat' : 'Settings'}</TooltipContent>}
            </Tooltip>
            {/* Theme toggle */}
            <Tooltip>
              <TooltipTrigger>
                <button
                  onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
                  className="flex items-center gap-2 px-3 py-2 min-h-[44px] rounded-md text-sm transition-colors w-full text-muted-foreground hover:bg-accent/50 hover:text-foreground mt-1"
                >
                  {theme === 'dark' ? <Sun className="h-4 w-4 shrink-0" /> : <Moon className="h-4 w-4 shrink-0" />}{!collapsed && 'Toggle Theme'}
                </button>
              </TooltipTrigger>
              {collapsed && <TooltipContent side="right">Toggle Theme</TooltipContent>}
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

        {/* Main content */}
        <main className="flex-1 flex flex-col min-w-0 overflow-hidden pt-[52px] lg:pt-0">
          <ErrorBoundary>
            <Outlet context={{
              activeConversationId: activeId,
              setActiveId,
              refreshConversations: loadConversations,
              socketRef,
              connected,
              setChatPanelOpen,
              setChatContext,
            }} />
          </ErrorBoundary>
        </main>
        
        {/* Contextual Chat Panel */}
        {chatPanelOpen && (
          <aside className="fixed inset-0 z-50 lg:static lg:border-l lg:border-border/40 lg:w-[400px] lg:min-w-[400px] bg-background flex flex-col overflow-hidden">
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
      </div>
    </TooltipProvider>
  )
}
