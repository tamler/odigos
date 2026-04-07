import { create } from 'zustand'
import type { ChatMessage } from '@/layouts/AppLayout'

interface ChatState {
  messages: ChatMessage[]
  setMessages: (messages: ChatMessage[] | ((prev: ChatMessage[]) => ChatMessage[])) => void
  addMessage: (message: ChatMessage, messageId?: string) => void
  updateLastMessage: (content: string) => void
  appendToLastMessage: (chunk: string) => void
  finalizeLastMessage: () => void
  finalizeStreaming: (fullContent: string) => void
  startStreaming: () => void
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
  streamingMessageId: string | null
  setStreamingMessageId: (id: string | null) => void
}

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  setMessages: (messages) => {
    if (typeof messages === 'function') {
      set((state) => ({ messages: messages(state.messages) }))
    } else {
      set({ messages })
    }
  },
  addMessage: (message, messageId?: string) => set((state) => ({
    messages: [...state.messages, message],
    // If this is an assistant message, mark streaming active atomically
    ...(message.role === 'assistant' ? { isStreaming: true, streamingMessageId: messageId || null } : {}),
  })),
  updateLastMessage: (content) =>
    set((state) => {
      const msgs = [...state.messages]
      if (msgs.length > 0) msgs[msgs.length - 1] = { ...msgs[msgs.length - 1], content }
      return { messages: msgs }
    }),
  appendToLastMessage: (chunk) =>
    set((state) => {
      const msgs = [...state.messages]
      if (msgs.length > 0) {
        const last = msgs[msgs.length - 1]
        msgs[msgs.length - 1] = { ...last, content: (last.content || '') + chunk }
      }
      return { messages: msgs, isStreaming: true }
    }),
  finalizeLastMessage: () =>
    set({ isStreaming: false, streamingMessageId: null }),
  finalizeStreaming: (fullContent: string) =>
    set((state) => {
      const msgs = [...state.messages]
      if (msgs.length > 0 && msgs[msgs.length - 1].role === 'assistant') {
        msgs[msgs.length - 1] = { ...msgs[msgs.length - 1], content: fullContent }
      }
      return { messages: msgs, isStreaming: false, streamingMessageId: null }
    }),
  startStreaming: () => set({ isStreaming: true }),
  thinking: false,
  setThinking: (thinking) => set({ thinking }),
  status: null,
  setStatus: (status) => set({ status }),
  queuedCount: 0,
  setQueuedCount: (count) => set({ queuedCount: count }),
  suggestedActions: [],
  setSuggestedActions: (actions) => set({ suggestedActions: actions }),
  activeConversationId: null,
  setActiveConversationId: (id) => set((state) => {
    // Only clear messages when SWITCHING to a different conversation.
    // Setting the ID for the first time (null → id) preserves current messages.
    const switching = state.activeConversationId !== null && state.activeConversationId !== id
    return {
      activeConversationId: id,
      ...(switching ? {
        messages: [],
        isStreaming: false,
        streamingMessageId: null,
        thinking: false,
        status: null,
        suggestedActions: [],
      } : {}),
    }
  }),
  isStreaming: false,
  streamingMessageId: null,
  setStreamingMessageId: (id) => set({ streamingMessageId: id }),
}))
