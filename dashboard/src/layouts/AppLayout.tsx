import { useState } from 'react'
import { Outlet, NavLink, useNavigate } from 'react-router-dom'
import { Settings, PanelLeftClose, PanelLeft, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { get } from '@/lib/api'
import { useEffect } from 'react'

interface Conversation {
  id: string
  created_at: string
  title?: string
}

export default function AppLayout() {
  const [collapsed, setCollapsed] = useState(false)
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const navigate = useNavigate()

  useEffect(() => {
    get<{ conversations: Conversation[] }>('/api/conversations?limit=50')
      .then((data) => setConversations(data.conversations))
      .catch(() => {})
  }, [])

  function handleNewChat() {
    setActiveId(null)
    navigate('/')
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
          </div>

          {/* Conversation list */}
          {!collapsed && (
            <ScrollArea className="flex-1 px-2">
              <div className="space-y-0.5 pb-4">
                {conversations.map((c) => (
                  <button
                    key={c.id}
                    onClick={() => { setActiveId(c.id); navigate('/') }}
                    className={`w-full text-left px-3 py-2 rounded-md text-sm truncate transition-colors ${
                      activeId === c.id
                        ? 'bg-accent text-accent-foreground'
                        : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground'
                    }`}
                  >
                    {c.title || c.id}
                  </button>
                ))}
              </div>
            </ScrollArea>
          )}

          {/* Bottom: Settings */}
          <div className="p-3 mt-auto">
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
          <Outlet />
        </main>
      </div>
    </TooltipProvider>
  )
}
