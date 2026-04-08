import { memo, useRef, useCallback } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
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
  Upload,
  Key,
  Activity
} from 'lucide-react'
import { NotebookSidebar } from '@/components/NotebookSidebar'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { get, uploadFile } from '@/lib/api'
import { toast } from 'sonner'
import { prefetchMessages } from '@/lib/prefetch'
import { useChatStore } from '@/stores/chatStore'
import { useUIStore } from '@/stores/uiStore'
import { useConversationStore } from '@/stores/conversationStore'
import { useNotificationStore } from '@/stores/notificationStore'
import { Artifact } from '@/components/ArtifactCard'
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
  { id: 'services', label: 'Services', icon: Key },
  { id: 'mesh', label: 'Mesh', icon: Network },
  { id: 'data', label: 'Data', icon: Database },
  { id: 'analytics', label: 'Analytics', icon: BarChart3 },
  { id: 'connections', label: 'Connections', icon: LinkIcon },
  { id: 'peers', label: 'Peers', icon: Network },
  { id: 'feed', label: 'Feed', icon: Rss },
  { id: 'inspector', label: 'Inspector', icon: Eye },
]

export interface AppSidebarProps {
  editingId: string | null
  editTitle: string
  setEditTitle: (title: string) => void
  confirmRename: () => void
  handleExport: (id: string, format: 'markdown' | 'json') => void
  handleDelete: (id: string) => void
  displayTitle: (c: Conversation) => string
  startRename: (c: Conversation | null) => void
  handleNewChat: () => void
  handleSelectConversation: (id: string) => void
  handleSelectImage: (id: string) => void
  pwaInstallable: boolean
  pwaInstall: () => void
}

export const AppSidebar = memo(({
  editingId, editTitle, setEditTitle,
  confirmRename, handleExport, handleDelete, displayTitle,
  startRename,
  handleNewChat, handleSelectConversation, handleSelectImage: _handleSelectImage,
  pwaInstallable, pwaInstall,
}: AppSidebarProps) => {
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
  const conversations = useConversationStore(s => s.conversations)
  const filteredConversations = searchQuery
    ? conversations.filter(c => (c.title || c.id.slice(0, 8)).toLowerCase().includes(searchQuery.toLowerCase()))
    : conversations
  const activeId = useChatStore(s => s.activeConversationId)
  const navigate = useNavigate()
  const location = useLocation()

  const isSettings = location.pathname.startsWith('/settings')
  const isNotebook = location.pathname.startsWith('/notebooks')
  const isKanban = location.pathname.startsWith('/kanban')
  const isImages = location.pathname.startsWith('/images')
  const isActivity = location.pathname === '/activity'
  const isChat = !isSettings && !isNotebook && !isKanban && !isImages && !isActivity
  const unreadCount = useNotificationStore((s) => s.unreadCount)
  const currentTab = location.pathname.split('/')[2] || 'general'

  const fileInputRef = useRef<HTMLInputElement>(null)
  const hoverTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const handleConversationHover = useCallback((conversationId: string) => {
    if (hoverTimerRef.current) clearTimeout(hoverTimerRef.current)
    hoverTimerRef.current = setTimeout(() => {
      prefetchMessages(conversationId)
    }, 200)
  }, [])

  const handleConversationHoverEnd = useCallback(() => {
    if (hoverTimerRef.current) {
      clearTimeout(hoverTimerRef.current)
      hoverTimerRef.current = null
    }
  }, [])

  const handleUploadClick = () => {
    fileInputRef.current?.click()
  }

  const onFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    try {
      await uploadFile(file)
      toast.success('Image uploaded')
      const imgData = await get<{ artifacts: Artifact[] }>('/api/artifacts')
      useConversationStore.getState().setImages(
        (imgData.artifacts || []).filter(a => a.content_type?.startsWith('image/')).slice(0, 10)
      )
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
            <button onClick={() => navigate('/activity')} className={`flex-1 p-2 rounded-lg flex items-center justify-center transition-colors relative ${isActivity ? 'bg-primary/10 text-primary shadow-inner' : 'text-muted-foreground hover:bg-muted'}`} title="Activity">
              <Activity className="h-4 w-4" />
              {unreadCount > 0 && <span className="absolute -top-0.5 -right-0.5 w-3.5 h-3.5 bg-purple-500 rounded-full text-[8px] text-white flex items-center justify-center font-bold">{unreadCount > 9 ? '!' : unreadCount}</span>}
            </button>
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
              <NotebookSidebar notebooks={notebooks} currentPath={location.pathname} onNavigate={(path) => { navigate(path); setSidebarOpen(false) }} />
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
                searchQuery ? <div className="px-3 py-6 mt-4 text-center text-xs text-muted-foreground italic">No conversations found</div> : null
              ) : (
                filteredConversations.map((c: any) => (
                  <div key={c.id} className="group relative mb-0.5" onMouseEnter={() => handleConversationHover(c.id)} onMouseLeave={handleConversationHoverEnd}>
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
                      <button onClick={() => handleSelectConversation(c.id)} className={`w-full text-left px-3 py-2 min-h-[40px] rounded-lg text-sm truncate pr-8 transition-all duration-200 ${activeId === c.id ? 'bg-primary/10 text-primary font-bold shadow-sm border-l-2 border-primary' : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground hover:translate-x-0.5'}`}>{displayTitle(c)}</button>
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
