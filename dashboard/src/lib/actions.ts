import { NavigateFunction } from 'react-router-dom'

export interface UIAction {
  action: 'navigate' | 'refresh' | 'open_chat' | 'create' | 'theme'
  to?: string
  type?: string
  value?: string
}

export function executeActions(
  actions: UIAction[],
  navigate: NavigateFunction,
  callbacks: {
    refresh: () => void
    openChat: () => void
    setTheme: (theme: string) => void
  }
): void {
  for (const a of actions) {
    console.log('[Actions] Executing:', a)
    switch (a.action) {
      case 'navigate':
        if (a.to) navigate(a.to)
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
      case 'create':
        // Future: handle specialized creation if needed
        break
    }
  }
}
