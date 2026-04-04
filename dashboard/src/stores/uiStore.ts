import { create } from 'zustand'

interface BackgroundTask {
  id: string
  toolName: string
  description: string
  startedAt: string
  conversationId: string
}

interface UIState {
  sidebarOpen: boolean
  setSidebarOpen: (open: boolean) => void
  collapsed: boolean
  setCollapsed: (collapsed: boolean) => void
  isMobile: boolean
  setIsMobile: (mobile: boolean) => void
  artifactPanelOpen: boolean
  setArtifactPanelOpen: (open: boolean) => void
  activeArtifactId: string | null
  setActiveArtifactId: (id: string | null) => void
  chatPanelOpen: boolean
  setChatPanelOpen: (open: boolean) => void
  focusMode: boolean
  setFocusMode: (mode: boolean) => void
  switcherOpen: boolean
  setSwitcherOpen: (open: boolean) => void
  connected: boolean
  setConnected: (connected: boolean) => void
  agentName: string
  setAgentName: (name: string) => void
  hasNewEmail: boolean
  setHasNewEmail: (hasNew: boolean) => void
  backgroundTasks: BackgroundTask[]
  addBackgroundTask: (task: BackgroundTask) => void
  removeBackgroundTask: (id: string) => void
  clearBackgroundTasks: () => void
}

export const useUIStore = create<UIState>((set) => ({
  sidebarOpen: false,
  setSidebarOpen: (open) => set({ sidebarOpen: open }),
  collapsed: false,
  setCollapsed: (collapsed) => set({ collapsed }),
  isMobile: typeof window !== 'undefined' ? window.innerWidth < 1024 : false,
  setIsMobile: (mobile) => set({ isMobile: mobile }),
  artifactPanelOpen: false,
  setArtifactPanelOpen: (open) => set({ artifactPanelOpen: open }),
  activeArtifactId: null,
  setActiveArtifactId: (id) => set({ activeArtifactId: id }),
  chatPanelOpen: false,
  setChatPanelOpen: (open) => set({ chatPanelOpen: open }),
  focusMode: false,
  setFocusMode: (mode) => set({ focusMode: mode }),
  switcherOpen: false,
  setSwitcherOpen: (open) => set({ switcherOpen: open }),
  connected: false,
  setConnected: (connected) => set({ connected }),
  agentName: 'Odigos',
  setAgentName: (name) => set({ agentName: name }),
  hasNewEmail: false,
  setHasNewEmail: (hasNew) => set({ hasNewEmail: hasNew }),
  backgroundTasks: [],
  addBackgroundTask: (task) => set((s) => ({
    backgroundTasks: [...s.backgroundTasks, task]
  })),
  removeBackgroundTask: (id) => set((s) => ({
    backgroundTasks: s.backgroundTasks.filter(t => t.id !== id)
  })),
  clearBackgroundTasks: () => set({ backgroundTasks: [] }),
}))
