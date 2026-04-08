import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { useEffect, useState, useCallback, lazy, Suspense } from 'react'
import { Toaster } from '@/components/ui/sonner'
import { getAuthStatus } from './lib/auth'
import AppLayout from './layouts/AppLayout'
import LoginPrompt from './components/LoginPrompt'
import WelcomeScreen from './components/WelcomeScreen'
import { Loader } from '@/components/ui/loader'
import { get } from './lib/api'
import ChatPage from './pages/ChatPage'
import NotFoundPage from './pages/NotFoundPage'

// Lazy load all pages except Chat (the default view)
const SettingsPage = lazy(() => import('./pages/SettingsPage'))
const NotebookPage = lazy(() => import('./pages/NotebookPage'))
const KanbanPage = lazy(() => import('./pages/KanbanPage'))
const ArtifactsPage = lazy(() => import('./pages/ArtifactsPage'))
const ImagesPage = lazy(() => import('./pages/ImagesPage'))
const ActivityPage = lazy(() => import('./pages/ActivityPage'))
const SharedNotebookPage = lazy(() => import('./pages/SharedNotebookPage'))
const SharedBoardPage = lazy(() => import('./pages/SharedBoardPage'))

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
    return (
      <div className="flex flex-col items-center justify-center h-screen gap-6 animate-in fade-in duration-500">
        <Loader variant="text-shimmer" text="Odigos" size="lg" className="text-3xl font-bold tracking-tight" />
        <Loader variant="pulse" size="sm" />
      </div>
    )
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
          <Routes>
            {/* Shared routes — lazy loaded, rarely visited */}
            <Route path="/shared/notebook/:token" element={
              <Suspense fallback={<div className="flex items-center justify-center h-screen"><Loader /></div>}>
                <SharedNotebookPage />
              </Suspense>
            } />
            <Route path="/shared/board/:token" element={
              <Suspense fallback={<div className="flex items-center justify-center h-screen"><Loader /></div>}>
                <SharedBoardPage />
              </Suspense>
            } />

            <Route element={<AppLayout />}>
              <Route path="/" element={<ChatPage />} />
              <Route path="/settings" element={<Suspense fallback={null}><SettingsPage /></Suspense>} />
              <Route path="/settings/:tab" element={<Suspense fallback={null}><SettingsPage /></Suspense>} />
              <Route path="/notebooks" element={<Suspense fallback={null}><NotebookPage /></Suspense>} />
              <Route path="/notebooks/:id" element={<Suspense fallback={null}><NotebookPage /></Suspense>} />
              <Route path="/kanban" element={<Suspense fallback={null}><KanbanPage /></Suspense>} />
              <Route path="/kanban/:id" element={<Suspense fallback={null}><KanbanPage /></Suspense>} />
              <Route path="/artifacts" element={<Suspense fallback={null}><ArtifactsPage /></Suspense>} />
              <Route path="/images" element={<Suspense fallback={null}><ImagesPage /></Suspense>} />
              <Route path="/activity" element={<Suspense fallback={null}><ActivityPage /></Suspense>} />
              <Route path="*" element={<NotFoundPage />} />
            </Route>
          </Routes>
        </BrowserRouter>
      )}
    </>
  )
}
