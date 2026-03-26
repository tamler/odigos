import { useLocation, useParams } from 'react-router-dom'

export interface PageContext {
  page: string
  page_id?: string
  page_title?: string
  visible_data?: string
}

export function usePageContext(): PageContext {
  const location = useLocation()
  const params = useParams()
  const path = location.pathname

  // Default context from URL
  if (path.startsWith('/kanban')) {
    return { page: 'kanban', page_id: params.id }
  }
  if (path.startsWith('/notebooks')) {
    return { page: 'notebook', page_id: params.id }
  }
  if (path.startsWith('/settings')) {
    const tab = path.split('/')[2] || 'general'
    return { page: 'settings', page_id: tab }
  }
  if (path.startsWith('/artifacts')) {
    return { page: 'artifacts' }
  }

  const page = path.split('/')[1] || 'home'
  return { page }
}
