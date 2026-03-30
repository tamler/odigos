import { NavigateFunction } from 'react-router-dom'

export interface UIAction {
  action: 'navigate' | 'refresh' | 'open_chat' | 'create' | 'theme' | 'navigate-to-notebook' | 'navigate-to-board' | 'stop_tts' | 'highlight'
  to?: string
  type?: string
  value?: string
  selector?: string
  title?: string
  description?: string
}

export function executeActions(
  actions: UIAction[],
  navigate: NavigateFunction,
  callbacks: {
    refresh: () => void
    openChat: () => void
    setTheme: (theme: string) => void
    stopTTS: () => void
    highlight?: (selector: string, title: string, description: string) => void
  }
): void {
  for (const a of actions) {
    switch (a.action) {
      case 'navigate':
        if (a.to && a.to.startsWith('/')) navigate(a.to)
        break
      case 'navigate-to-notebook':
        if (a.value) navigate(`/notebooks/${a.value}`)
        break
      case 'navigate-to-board':
        if (a.value) navigate(`/kanban/${a.value}`)
        break
      case 'refresh':
        callbacks.refresh()
        break
      case 'open_chat':
        callbacks.openChat()
        break
      case 'theme':
        if (a.value) callbacks.setTheme(a.value)
        break
      case 'stop_tts':
        callbacks.stopTTS()
        break
      case 'highlight':
        if (a.selector && callbacks.highlight)
          callbacks.highlight(a.selector, a.title || '', a.description || '')
        break
      case 'create':
        break
    }
  }
}
