import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { useEffect, useState, useCallback, lazy, Suspense } from 'react'
import { Toaster } from '@/components/ui/sonner'
import { getAuthStatus } from './lib/auth'
import AppLayout from './layouts/AppLayout'
import ChatPage from './pages/ChatPage'
import LoginPrompt from './components/LoginPrompt'
import WelcomeScreen from './components/WelcomeScreen'
import { Loader } from '@/components/ui/loader'
import { get } from './lib/api'

const SettingsPage = lazy(() => import('./pages/SettingsPage'))
const NotebookPage = lazy(() => import('./pages/NotebookPage'))
const KanbanPage = lazy(() => import('./pages/KanbanPage'))
const NotFoundPage = lazy(() => import('./pages/NotFoundPage'))
const ArtifactsPage = lazy(() => import('./pages/ArtifactsPage'))

// Load saved chat text size preference
const savedSize = localStorage.getItem('chat-text-size')
if (savedSize && savedSize !== 'medium') {
  document.body.setAttribute('data-chat-size', savedSize)
}

interface AuthState {
  setup_required: boolean
  authenticated: boolean
  must_change_password: boolean
}

export default function App() {
  const [authState, setAuthState] = useState<AuthState | null>(null)
  const [showWelcome, setShowWelcome] = useState(false)
  const [checkingWelcome, setCheckingWelcome] = useState(true)

  const checkAuth = useCallback(() => {
    getAuthStatus()
      .then(async (state) => {
        setAuthState(state)
        if (state.authenticated && !state.must_change_password && !state.setup_required) {
          // Check if we should show welcome screen (G49)
          const isSelected = localStorage.getItem('profile-selected') === 'true'
          if (!isSelected) {
            try {
              const res = await get<{ total: number }>('/api/conversations?limit=1')
              if (res.total === 0) {
                setShowWelcome(true)
              } else {
                localStorage.setItem('profile-selected', 'true')
              }
            } catch {
              // Ignore error, default to no welcome
            }
          }
        }
        setCheckingWelcome(false)
      })
      .catch(() => {
        setAuthState({ setup_required: false, authenticated: false, must_change_password: false })
        setCheckingWelcome(false)
      })
  }, [])

  useEffect(() => { checkAuth() }, [checkAuth])

  if (authState === null || checkingWelcome) {
    return <div className="flex items-center justify-center h-screen text-muted-foreground text-sm">Loading...</div>
  }

  const needsLogin = authState.setup_required || !authState.authenticated || authState.must_change_password

  if (!needsLogin && showWelcome) {
    return <WelcomeScreen onComplete={() => setShowWelcome(false)} />
  }

  return (
    <>
      <Toaster position="top-right" richColors />
      {needsLogin ? (
        <LoginPrompt
          setupRequired={authState.setup_required}
          mustChangePassword={authState.must_change_password}
          onAuth={checkAuth}
        />
      ) : (
        <BrowserRouter>
          <Suspense fallback={<div className="flex items-center justify-center h-screen"><Loader /></div>}>
            <Routes>
              <Route element={<AppLayout />}>
                <Route path="/" element={<ChatPage />} />
                <Route path="/settings" element={<SettingsPage />} />
                <Route path="/notebooks" element={<NotebookPage />} />
                <Route path="/notebooks/:id" element={<NotebookPage />} />
                <Route path="/kanban" element={<KanbanPage />} />
                <Route path="/kanban/:id" element={<KanbanPage />} />
                <Route path="/artifacts" element={<ArtifactsPage />} />
                <Route path="*" element={<NotFoundPage />} />
              </Route>
            </Routes>
          </Suspense>
        </BrowserRouter>
      )}
    </>
  )
}
