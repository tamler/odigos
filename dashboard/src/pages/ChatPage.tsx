import { useEffect } from 'react'
import { useOutletContext } from 'react-router-dom'
import { ChatSocket } from '@/lib/ws'
import { ChatPanel } from '@/components/ChatPanel'
import { PageTransition } from '@/components/ui/page-transition'
import { useChatStore } from '@/stores/chatStore'
import { useUIStore } from '@/stores/uiStore'

interface OutletCtx {
  socketRef: React.MutableRefObject<ChatSocket | null>
  playTTS?: () => void
  stopTTS?: () => void
  isTTSPlaying?: boolean
}

export default function ChatPage() {
  const activeConversationId = useChatStore(s => s.activeConversationId)
  const connected = useUIStore(s => s.connected)
  const setChatPanelOpen = useUIStore(s => s.setChatPanelOpen)
  const { socketRef } = useOutletContext<OutletCtx>()

  useEffect(() => {
    if (setChatPanelOpen) setChatPanelOpen(false)
  }, [setChatPanelOpen])

  return (
    <PageTransition className="flex-1 flex flex-col h-full bg-background relative z-10">
      <ChatPanel
        activeConversationId={activeConversationId}
        socketRef={socketRef}
        connected={connected}
        isSidePanel={false}
      />
    </PageTransition>
  )
}
