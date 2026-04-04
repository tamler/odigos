import { useLocation } from 'react-router-dom'

export function useRouteState() {
  const { pathname } = useLocation()
  return {
    isSettings: pathname.startsWith('/settings'),
    isNotebook: pathname.startsWith('/notebooks'),
    isKanban: pathname.startsWith('/kanban'),
    isImages: pathname.startsWith('/images'),
  }
}
