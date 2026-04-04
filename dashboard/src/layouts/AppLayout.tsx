import { useState, useEffect, useCallback, useRef } from 'react'
import { Outlet, useNavigate, useSearchParams, useLocation } from 'react-router-dom'
import {
  Menu,
  MessageCircle,
} from 'lucide-react'
import { ChatPanel } from '@/components/ChatPanel'
import { ArtifactPreview } from '@/components/ArtifactPreview'
import { QuickSwitcher } from '@/components/QuickSwitcher'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { Button } from '@/components/ui/button'
import { TooltipProvider } from '@/components/ui/tooltip'
import { get } from '@/lib/api'
import { usePwaInstall } from '@/hooks/usePwaInstall'
import { Artifact } from '@/components/ArtifactCard'
import { useChatStore } from '@/stores/chatStore'
import { useUIStore } from '@/stores/uiStore'
import { useConversationStore } from '@/stores/conversationStore'
import { AppSidebar } from './AppSidebar'
import { useRouteState } from './hooks/useRouteState'
import { useKeyboardShortcuts } from './hooks/useKeyboardShortcuts'
import { useConversationActions } from './hooks/useConversationActions'
import { useWebSocketHandler } from './hooks/useWebSocketHandler'

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
}

export default function AppLayout() {
  const [chatContext, setChatContext] = useState<Record<string, string> | undefined>(undefined)
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const pendingTitles = useRef<Record<string, string>>({})

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

  const { installable: pwaInstallable, install: pwaInstall } = usePwaInstall()

  const { isSettings, isNotebook, isKanban, isImages } = useRouteState()

  const {
    editingId, editTitle, setEditTitle,
    handleNewChat, handleSelectConversation, handleSelectImage,
    startRename, confirmRename, handleDelete, handleExport, displayTitle,
  } = useConversationActions()

  useKeyboardShortcuts({ onNewChat: handleNewChat })

  const { socketRef, playTTS, stopTTS, isTTSPlaying, driverHighlight } = useWebSocketHandler(pendingTitles)

  useEffect(() => {
    const handleResize = () => useUIStore.getState().setIsMobile(window.innerWidth < 1024)
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
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

  useEffect(() => { loadConversations() }, [loadConversations])

  useEffect(() => {
    const cid = searchParams.get('c')
    if (cid) setActiveConversationId(cid)
  }, [searchParams, setActiveConversationId])

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
