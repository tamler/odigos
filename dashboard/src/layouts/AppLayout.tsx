import { useState, useEffect, useCallback, useRef } from 'react'
import { Outlet, useNavigate, useSearchParams, useLocation } from 'react-router-dom'
import { Settings, PanelLeftClose, PanelLeft, Plus, Pencil, Trash2, Check, X, Download, MoreHorizontal, Menu, MessageSquare } from 'lucide-react'
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
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editTitle, setEditTitle] = useState('')
  const [connected, setConnected] = useState(false)
  const editInputRef = useRef<HTMLInputElement>(null)
  const socketRef = useRef<ChatSocket | null>(null)
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams] = useSearchParams()

  // Persistent WebSocket — lives at layout level, survives page navigation
  useEffect(() => {
    const socket = new ChatSocket(
      () => {},  // message handling delegated to ChatPage via ref
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
  }, [])

  const loadConversations = useCallback(() => {
    get<{ conversations: Conversation[] }>('/api/conversations?limit=50')
      .then((data) => setConversations(data.conversations))
      .catch(() => {})
  }, [])

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
    navigate('/')
  }

  function handleSelectConversation(id: string) {
    setActiveId(id)
    setSidebarOpen(false)
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

  const isSettingsPage = location.pathname === '/settings'

  return (
    <TooltipProvider>
      <div className="flex h-screen bg-background text-foreground">
        {/* Mobile top bar */}
        <div className="flex items-center gap-2 p-3 border-b border-border/40 lg:hidden fixed top-0 left-0 right-0 z-20 bg-background">
          <Button variant="ghost" size="icon" onClick={() => setSidebarOpen(true)}>
            <Menu className="h-5 w-5" />
          </Button>
          <button onClick={() => navigate('/')} className="text-sm font-semibold hover:text-muted-foreground transition-colors">Odigos</button>
          <Button variant="ghost" size="icon" className="ml-auto" onClick={handleNewChat}>
            <Plus className="h-5 w-5" />
          </Button>
        </div>

        {/* Sidebar */}
        <aside className={`fixed inset-y-0 left-0 z-40 w-64 flex flex-col border-r border-border/40 bg-background transition-transform duration-200 ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'} lg:static lg:translate-x-0 ${collapsed ? 'lg:w-14' : 'lg:w-64'}`}>
          {/* Top: Toggle + New Chat */}
          <div className="flex items-center gap-2 p-3">
            <Tooltip>
              <TooltipTrigger>
                <Button variant="ghost" size="icon" onClick={() => setCollapsed(!collapsed)} className="shrink-0">
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

          {/* Conversation list */}
          {!collapsed && (
            <ScrollArea className="flex-1 px-2">
              <div className="space-y-0.5 pb-4">
                {conversations.map((c) => (
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
                        <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0" onClick={confirmRename}>
                          <Check className="h-3 w-3" />
                        </Button>
                        <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0" onClick={() => setEditingId(null)}>
                          <X className="h-3 w-3" />
                        </Button>
                      </div>
                    ) : (
                      <button
                        onClick={() => handleSelectConversation(c.id)}
                        className={`w-full text-left px-3 py-2 rounded-md text-sm truncate transition-colors pr-8 ${
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
                            <Button variant="ghost" size="icon" className="h-6 w-6">
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
                ))}
              </div>
            </ScrollArea>
          )}

          {/* Bottom: Chat + Settings */}
          <div className="p-3 mt-auto space-y-1">
            <Tooltip>
              <TooltipTrigger>
                <button
                  onClick={() => { setSidebarOpen(false); navigate('/') }}
                  className={`flex items-center gap-2 px-3 py-2 rounded-md text-sm transition-colors w-full ${
                    !isSettingsPage ? 'bg-accent text-accent-foreground' : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground'
                  }`}
                >
                  <MessageSquare className="h-4 w-4 shrink-0" />
                  {!collapsed && 'Chat'}
                </button>
              </TooltipTrigger>
              {collapsed && <TooltipContent side="right">Chat</TooltipContent>}
            </Tooltip>
            <Tooltip>
              <TooltipTrigger>
                <button
                  onClick={() => { setSidebarOpen(false); navigate('/settings') }}
                  className={`flex items-center gap-2 px-3 py-2 rounded-md text-sm transition-colors w-full ${
                    isSettingsPage ? 'bg-accent text-accent-foreground' : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground'
                  }`}
                >
                  <Settings className="h-4 w-4 shrink-0" />
                  {!collapsed && 'Settings'}
                </button>
              </TooltipTrigger>
              {collapsed && <TooltipContent side="right">Settings</TooltipContent>}
            </Tooltip>
          </div>
        </aside>

        {/* Backdrop for mobile sidebar */}
        {sidebarOpen && (
          <div
            className="fixed inset-0 z-30 bg-black/50 lg:hidden"
            onClick={() => setSidebarOpen(false)}
          />
        )}

        {/* Main content */}
        <main className="flex-1 flex flex-col overflow-hidden pt-[52px] lg:pt-0">
          <Outlet context={{
            activeConversationId: activeId,
            setActiveId,
            refreshConversations: loadConversations,
            socketRef,
            connected,
          }} />
        </main>
      </div>
    </TooltipProvider>
  )
}
