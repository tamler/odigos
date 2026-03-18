import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { useEffect, useState, useCallback } from 'react'
import { Toaster } from '@/components/ui/sonner'
import { getAuthStatus } from './lib/auth'
import AppLayout from './layouts/AppLayout'
import ChatPage from './pages/ChatPage'
import SettingsPage from './pages/SettingsPage'
import NotebookPage from './pages/NotebookPage'
import LoginPrompt from './components/LoginPrompt'

interface AuthState {
  setup_required: boolean
  authenticated: boolean
  must_change_password: boolean
}

export default function App() {
  const [authState, setAuthState] = useState<AuthState | null>(null)

  const checkAuth = useCallback(() => {
    getAuthStatus()
      .then(setAuthState)
      .catch(() => setAuthState({ setup_required: false, authenticated: false, must_change_password: false }))
  }, [])

  useEffect(() => { checkAuth() }, [checkAuth])

  if (authState === null) {
    return <div className="flex items-center justify-center h-screen text-muted-foreground text-sm">Loading...</div>
  }

  const needsLogin = authState.setup_required || !authState.authenticated || authState.must_change_password

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
            <Route element={<AppLayout />}>
              <Route path="/" element={<ChatPage />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route path="/notebooks" element={<NotebookPage />} />
              <Route path="/notebooks/:id" element={<NotebookPage />} />
            </Route>
          </Routes>
        </BrowserRouter>
      )}
    </>
  )
}
