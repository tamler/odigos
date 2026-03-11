import { useState, useEffect, useCallback, useRef } from 'react'
import { Outlet, NavLink, useNavigate, useSearchParams } from 'react-router-dom'
import { Settings, PanelLeftClose, PanelLeft, Plus, Pencil, Trash2, Check, X, Activity, Users } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { get, patch, del } from '@/lib/api'
import { toast } from 'sonner'

interface Conversation {
  id: string
  created_at: string
  last_message_at: string
  title?: string | null
  message_count: number
}

export default function AppLayout() {
  const [collapsed, setCollapsed] = useState(false)
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editTitle, setEditTitle] = useState('')
  const editInputRef = useRef<HTMLInputElement>(null)
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  const loadConversations = useCallback(() => {
    get<{ conversations: Conversation[] }>('/api/conversations?limit=50')
      .then((data) => setConversations(data.conversations))
      .catch(() => {})
  }, [])

  useEffect(() => {
    loadConversations()
  }, [loadConversations])

  // Pick up conversation ID from URL
  useEffect(() => {
    const cid = searchParams.get('c')
    if (cid) setActiveId(cid)
  }, [searchParams])

  // Focus edit input when editing starts
  useEffect(() => {
    if (editingId) editInputRef.current?.focus()
  }, [editingId])

  function handleNewChat() {
    setActiveId(null)
    navigate('/')
  }

  function handleSelectConversation(id: string) {
    setActiveId(id)
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

  function displayTitle(c: Conversation): string {
    if (c.title) return c.title
    // Fallback: short ID + date
    const date = new Date(c.created_at || c.last_message_at)
    const short = date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
    return `Chat ${short}`
  }

  return (
    <TooltipProvider>
      <div className="flex h-screen bg-background text-foreground">
        {/* Sidebar */}
        <aside className={`${collapsed ? 'w-14' : 'w-64'} flex flex-col border-r border-border/40 transition-all duration-200`}>
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
            {collapsed && (
              <Tooltip>
                <TooltipTrigger>
                  <Button variant="ghost" size="icon" onClick={handleNewChat} className="shrink-0">
                    <Plus className="h-4 w-4" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="right">New Chat</TooltipContent>
              </Tooltip>
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
                      <div className="absolute right-1 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 transition-opacity">
                        <DropdownMenu>
                          <DropdownMenuTrigger>
                            <Button variant="ghost" size="icon" className="h-6 w-6">
                              <Pencil className="h-3 w-3" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end" className="w-36">
                            <DropdownMenuItem onClick={() => startRename(c)}>
                              <Pencil className="h-3 w-3 mr-2" /> Rename
                            </DropdownMenuItem>
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

          {/* Bottom: Evolution + Settings */}
          <div className="p-3 mt-auto space-y-1">
            <Tooltip>
              <TooltipTrigger>
                <NavLink
                  to="/evolution"
                  className={({ isActive }) =>
                    `flex items-center gap-2 px-3 py-2 rounded-md text-sm transition-colors ${
                      isActive ? 'bg-accent text-accent-foreground' : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground'
                    }`
                  }
                >
                  <Activity className="h-4 w-4 shrink-0" />
                  {!collapsed && 'Evolution'}
                </NavLink>
              </TooltipTrigger>
              {collapsed && <TooltipContent side="right">Evolution</TooltipContent>}
            </Tooltip>
            <Tooltip>
              <TooltipTrigger>
                <NavLink
                  to="/agents"
                  className={({ isActive }) =>
                    `flex items-center gap-2 px-3 py-2 rounded-md text-sm transition-colors ${
                      isActive ? 'bg-accent text-accent-foreground' : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground'
                    }`
                  }
                >
                  <Users className="h-4 w-4 shrink-0" />
                  {!collapsed && 'Agents'}
                </NavLink>
              </TooltipTrigger>
              {collapsed && <TooltipContent side="right">Agents</TooltipContent>}
            </Tooltip>
            <Tooltip>
              <TooltipTrigger>
                <NavLink
                  to="/settings"
                  className={({ isActive }) =>
                    `flex items-center gap-2 px-3 py-2 rounded-md text-sm transition-colors ${
                      isActive ? 'bg-accent text-accent-foreground' : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground'
                    }`
                  }
                >
                  <Settings className="h-4 w-4 shrink-0" />
                  {!collapsed && 'Settings'}
                </NavLink>
              </TooltipTrigger>
              {collapsed && <TooltipContent side="right">Settings</TooltipContent>}
            </Tooltip>
          </div>
        </aside>

        {/* Main content */}
        <main className="flex-1 flex flex-col overflow-hidden">
          <Outlet context={{ activeConversationId: activeId, setActiveId, refreshConversations: loadConversations }} />
        </main>
      </div>
    </TooltipProvider>
  )
}
