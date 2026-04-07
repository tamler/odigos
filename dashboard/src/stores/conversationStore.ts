import { create } from 'zustand'
import { get as apiGet } from '@/lib/api'
import type { Artifact } from '@/components/ArtifactCard'

interface Conversation {
  id: string
  created_at: string
  last_message_at: string | null
  title?: string | null
  message_count: number
}

interface ConversationState {
  conversations: Conversation[]
  setConversations: (conversations: Conversation[] | ((prev: Conversation[]) => Conversation[])) => void
  refreshConversations: (pendingTitles?: Record<string, string>) => Promise<void>
  notebooks: { id: string; title: string; mode?: string; updated_at: string }[]
  setNotebooks: (notebooks: { id: string; title: string; mode?: string; updated_at: string }[] | ((prev: { id: string; title: string; mode?: string; updated_at: string }[]) => { id: string; title: string; mode?: string; updated_at: string }[])) => void
  boards: { id: string; title: string; mode?: string; updated_at: string }[]
  setBoards: (boards: { id: string; title: string; mode?: string; updated_at: string }[] | ((prev: { id: string; title: string; mode?: string; updated_at: string }[]) => { id: string; title: string; mode?: string; updated_at: string }[])) => void
  images: Artifact[]
  setImages: (images: Artifact[]) => void
  searchQuery: string
  setSearchQuery: (query: string) => void
  filteredConversations: () => Conversation[]
}

export type { Conversation }

export const useConversationStore = create<ConversationState>((set, get) => ({
  conversations: [],
  setConversations: (conversations) => {
    if (typeof conversations === 'function') {
      set((state) => ({ conversations: conversations(state.conversations) }))
    } else {
      set({ conversations })
    }
  },
  refreshConversations: async (pendingTitles) => {
    try {
      const data = await apiGet<{ conversations: Conversation[] }>('/api/conversations?limit=50')
      set({
        conversations: data.conversations.map((c) => ({
          ...c,
          title: pendingTitles?.[c.id] || c.title,
        })),
      })
    } catch {}
  },
  notebooks: [],
  setNotebooks: (notebooks) => {
    if (typeof notebooks === 'function') {
      set((state) => ({ notebooks: notebooks(state.notebooks) }))
    } else {
      set({ notebooks })
    }
  },
  boards: [],
  setBoards: (boards) => {
    if (typeof boards === 'function') {
      set((state) => ({ boards: boards(state.boards) }))
    } else {
      set({ boards })
    }
  },
  images: [],
  setImages: (images) => set({ images }),
  searchQuery: '',
  setSearchQuery: (query) => set({ searchQuery: query }),
  filteredConversations: () => {
    const { conversations, searchQuery } = get()
    if (!searchQuery) return conversations
    const q = searchQuery.toLowerCase()
    return conversations.filter((c) => {
      const title = c.title || c.id.slice(0, 8)
      return title.toLowerCase().includes(q)
    })
  },
}))
