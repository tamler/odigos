import { create } from 'zustand'
import type { ChatMessage } from '@/layouts/AppLayout'

interface ChatState {
  messages: ChatMessage[]
  setMessages: (messages: ChatMessage[] | ((prev: ChatMessage[]) => ChatMessage[])) => void
  addMessage: (message: ChatMessage) => void
  updateLastMessage: (content: string) => void
  promoteStreaming: (fallbackContent?: string) => void
  streamingContent: string
  setStreamingContent: (content: string | ((prev: string) => string)) => void
  thinking: boolean
  setThinking: (thinking: boolean) => void
  status: string | null
  setStatus: (status: string | null) => void
  queuedCount: number
  setQueuedCount: (count: number) => void
  suggestedActions: string[]
  setSuggestedActions: (actions: string[]) => void
  activeConversationId: string | null
  setActiveConversationId: (id: string | null) => void
  isStreaming: boolean
}

export const useChatStore = create<ChatState>((set, get) => ({
  messages: [],
  setMessages: (messages) => {
    if (typeof messages === 'function') {
      set((state) => ({ messages: messages(state.messages) }))
    } else {
      set({ messages })
    }
  },
  addMessage: (message) => set((state) => ({ messages: [...state.messages, message] })),
  promoteStreaming: (fallbackContent) => set((state) => {
    const content = state.streamingContent || fallbackContent || ''
    if (!content) return { streamingContent: '', isStreaming: false }
    return {
      messages: [...state.messages, {
        role: 'assistant' as const,
        content,
        timestamp: new Date().toISOString(),
      }],
      streamingContent: '',
      isStreaming: false,
    }
  }),
  updateLastMessage: (content) =>
    set((state) => {
      const msgs = [...state.messages]
      if (msgs.length > 0) msgs[msgs.length - 1] = { ...msgs[msgs.length - 1], content }
      return { messages: msgs }
    }),
  streamingContent: '',
  setStreamingContent: (content) => {
    if (typeof content === 'function') {
      set((state) => ({ streamingContent: content(state.streamingContent), isStreaming: true }))
    } else {
      set({ streamingContent: content, isStreaming: content !== '' })
    }
  },
  thinking: false,
  setThinking: (thinking) => set({ thinking, ...(thinking ? {} : { isStreaming: false }) }),
  status: null,
  setStatus: (status) => set({ status }),
  queuedCount: 0,
  setQueuedCount: (count) => set({ queuedCount: count }),
  suggestedActions: [],
  setSuggestedActions: (actions) => set({ suggestedActions: actions }),
  activeConversationId: null,
  setActiveConversationId: (id) => set({ activeConversationId: id }),
  get isStreaming() {
    return get().streamingContent !== ''
  },
}))
