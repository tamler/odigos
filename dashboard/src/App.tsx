import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { get } from './lib/api'
import { isAuthenticated } from './lib/auth'
import AppLayout from './layouts/AppLayout'
import ChatPage from './pages/ChatPage'
import SettingsPage from './pages/SettingsPage'
import LoginPrompt from './components/LoginPrompt'

export default function App() {
  const [setupDone, setSetupDone] = useState<boolean | null>(null)
  const [authed, setAuthed] = useState(isAuthenticated())

  useEffect(() => {
    get<{ configured: boolean }>('/api/setup-status')
      .then((data) => setSetupDone(data.configured))
      .catch(() => setSetupDone(false))
  }, [])

  if (setupDone === null) {
    return <div className="flex items-center justify-center h-screen text-muted-foreground">Loading...</div>
  }

  if (setupDone && !authed) {
    return <LoginPrompt onLogin={() => setAuthed(true)} />
  }

  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppLayout />}>
          <Route path="/" element={setupDone && authed ? <ChatPage /> : <Navigate to="/settings" />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
