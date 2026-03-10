import { useState } from 'preact/hooks'
import { html } from '../lib/htm.js'
import { ChatPage } from '../pages/ChatPage.js'
import { DashboardPage } from '../pages/DashboardPage.js'
import { SettingsPage } from '../pages/SettingsPage.js'

const PAGES = { chat: ChatPage, dashboard: DashboardPage, settings: SettingsPage }

export function App() {
  const [page, setPage] = useState('chat')
  const Page = PAGES[page] || ChatPage

  return html`
    <div class="layout">
      <nav class="sidebar">
        <h1>Odigos</h1>
        <a class=${page === 'chat' ? 'active' : ''} href="#" onClick=${(e) => { e.preventDefault(); setPage('chat') }}>Chat</a>
        <a class=${page === 'dashboard' ? 'active' : ''} href="#" onClick=${(e) => { e.preventDefault(); setPage('dashboard') }}>Dashboard</a>
        <a class=${page === 'settings' ? 'active' : ''} href="#" onClick=${(e) => { e.preventDefault(); setPage('settings') }}>Settings</a>
      </nav>
      <main class="main">
        <${Page} />
      </main>
    </div>
  `
}
