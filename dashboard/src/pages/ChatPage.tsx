import { useEffect } from 'react'
import { useOutletContext } from 'react-router-dom'
import { ChatSocket } from '@/lib/ws'
import { ChatPanel } from '@/components/ChatPanel'

interface OutletCtx {
  activeConversationId: string | null
  setActiveId: (id: string | null) => void
  refreshConversations: () => void
  socketRef: React.MutableRefObject<ChatSocket | null>
  connected: boolean
  setChatPanelOpen: (open: boolean) => void
}

export default function ChatPage() {
  const {
    activeConversationId,
    setActiveId,
    refreshConversations,
    socketRef,
    connected,
    setChatPanelOpen,
  } = useOutletContext<OutletCtx>()

  useEffect(() => {
    // Ensure side panel is closed when visiting full chat page
    if (setChatPanelOpen) setChatPanelOpen(false)
  }, [setChatPanelOpen])

  return (
    <div className="flex-1 flex flex-col h-full bg-background relative z-10">
      <ChatPanel
        activeConversationId={activeConversationId}
        setActiveId={setActiveId}
        refreshConversations={refreshConversations}
        socketRef={socketRef}
        connected={connected}
        isSidePanel={false}
      />
    </div>
  )
}
