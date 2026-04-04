import { useEffect } from 'react'
import { useUIStore } from '@/stores/uiStore'

export function useKeyboardShortcuts(callbacks: {
  onNewChat: () => void
}) {
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        useUIStore.getState().setSwitcherOpen(true)
        return
      }

      if (['INPUT', 'TEXTAREA'].includes((e.target as HTMLElement).tagName) || (e.target as HTMLElement).isContentEditable) {
        if (e.key === 'Escape') {
          (e.target as HTMLElement).blur()
          useUIStore.getState().setSidebarOpen(false)
          useUIStore.getState().setChatPanelOpen(false)
        }
        return
      }

      if (e.key === 'Escape') {
        useUIStore.getState().setSidebarOpen(false)
        useUIStore.getState().setChatPanelOpen(false)
      } else if (e.key === 'n' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        callbacks.onNewChat()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])
}
