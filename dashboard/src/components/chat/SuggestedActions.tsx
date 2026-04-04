import { useChatStore } from '@/stores/chatStore'
import type { ChatMessage } from '@/layouts/AppLayout'

interface SuggestedActionsProps {
  actions: string[]
  showAll: boolean
  onToggleShowAll: () => void
  activeConversationId: string | null
  socketRef: React.MutableRefObject<import('@/lib/ws').ChatSocket | null>
  setMessages: (updater: (prev: ChatMessage[]) => ChatMessage[]) => void
  isSidePanel: boolean
}

export function SuggestedActions({
  actions,
  showAll,
  onToggleShowAll,
  activeConversationId,
  socketRef,
  setMessages,
  isSidePanel,
}: SuggestedActionsProps) {
  if (actions.length === 0) return null

  const handleSelect = (action: string) => {
    useChatStore.getState().setSuggestedActions([])
    setMessages((prev: ChatMessage[]) => [...prev, { role: 'user', content: action, timestamp: new Date().toISOString() }])
    useChatStore.getState().setThinking(true)
    socketRef.current?.send('chat', { content: action, conversation_id: activeConversationId || undefined })
  }

  const handleDoAll = () => {
    useChatStore.getState().setSuggestedActions([])
    const allMsg = `Do all of these: ${actions.join(', ')}`
    setMessages((prev: ChatMessage[]) => [...prev, { role: 'user', content: allMsg, timestamp: new Date().toISOString() }])
    useChatStore.getState().setThinking(true)
    socketRef.current?.send('chat', { content: allMsg, conversation_id: activeConversationId || undefined })
  }

  return (
    <div className="px-4 pt-2">
      <div className={`w-full mx-auto flex flex-wrap gap-2 ${!isSidePanel ? 'max-w-[52rem]' : ''}`}>
        {(showAll ? actions : actions.slice(0, 5)).map((action: string, i: number) => (
          <button
            key={i}
            onClick={() => handleSelect(action)}
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded-full text-[13px] bg-muted/50 text-muted-foreground hover:bg-primary/10 hover:text-primary transition-all border border-border/40 hover:border-primary/20 shadow-sm animate-in fade-in slide-in-from-bottom-2 fill-mode-backwards will-change-transform"
            style={{ animationDelay: `${i * 75}ms` }}
          >
            {action.length > 60 ? action.slice(0, 57) + '...' : action}
          </button>
        ))}

        {actions.length > 5 && (
          <button
            onClick={onToggleShowAll}
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded-full text-[13px] text-muted-foreground hover:text-foreground transition-colors font-medium"
          >
            {showAll ? 'Show less' : `+${actions.length - 5} more`}
          </button>
        )}

        <button
          onClick={handleDoAll}
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-full text-[13px] bg-primary text-primary-foreground hover:bg-primary/90 transition-all shadow-md font-semibold ml-auto"
        >
          Do all
        </button>
      </div>
    </div>
  )
}
