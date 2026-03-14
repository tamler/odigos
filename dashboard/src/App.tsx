import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { Toaster } from '@/components/ui/sonner'
import { get } from './lib/api'
import { isAuthenticated, clearApiKey } from './lib/auth'
import AppLayout from './layouts/AppLayout'
import ChatPage from './pages/ChatPage'
import SettingsPage from './pages/SettingsPage'
import StatePage from './pages/StatePage'
import LoginPrompt from './components/LoginPrompt'

export default function App() {
  const [setupDone, setSetupDone] = useState<boolean | null>(null)
  const [authed, setAuthed] = useState(isAuthenticated())

  useEffect(() => {
    get<{ configured: boolean }>('/api/setup-status')
      .then((data) => setSetupDone(data.configured))
      .catch((err) => {
        if (err.message === 'unauthorized') {
          clearApiKey()
          setAuthed(false)
        }
        setSetupDone(false)
      })
  }, [])

  if (setupDone === null) {
    return <div className="flex items-center justify-center h-screen text-muted-foreground text-sm">Loading...</div>
  }

  return (
    <>
      <Toaster position="top-right" richColors />
      {setupDone && !authed ? (
        <LoginPrompt onLogin={() => setAuthed(true)} />
      ) : (
        <BrowserRouter>
          <Routes>
            <Route element={<AppLayout />}>
              <Route path="/" element={setupDone ? <ChatPage /> : <Navigate to="/settings" />} />
              <Route path="/settings" element={<SettingsPage needsSetup={!setupDone} />} />
              <Route path="/status" element={<StatePage />} />
            </Route>
          </Routes>
        </BrowserRouter>
      )}
    </>
  )
}
