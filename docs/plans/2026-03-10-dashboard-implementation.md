# Web Dashboard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a lightweight web dashboard served by FastAPI — chat, monitoring panels, and settings — using vanilla JS with vendored dependencies. No Node.js, no build step, fully offline-capable.

**Architecture:** Static files in `dashboard/` served by FastAPI. Preact (3KB) for UI components loaded as ES modules from vendored files. HTM for JSX-like templating without a build step. All JS dependencies vendored in `dashboard/vendor/`. Single `index.html` entry point with client-side routing via hash-based navigation. WebSocket for real-time chat.

**Tech Stack:** Preact + HTM (vendored ES modules), vanilla CSS with custom properties for theming, FastAPI static file serving.

**Why this stack:**
- Zero build step — edit files, refresh browser
- Fully offline — no CDN calls, everything vendored
- Tiny footprint — Preact+HTM < 10KB total
- Works with Ollama or any local LLM provider

---

## Context for the Implementer

**Vendored dependencies** go in `dashboard/vendor/`. Download these ES module builds:
- `preact.mjs` (~4KB) — from https://esm.sh/preact@10.25.4/+esm (pin version)
- `preact-hooks.mjs` (~2KB) — from https://esm.sh/preact@10.25.4/hooks/+esm
- `htm.mjs` (~1KB) — from https://esm.sh/htm@3.1.1/+esm

These are downloaded once and checked into the repo. No runtime network calls.

**Import map** in `index.html` maps bare specifiers to vendored files:
```html
<script type="importmap">
{
  "imports": {
    "preact": "/dashboard/vendor/preact.mjs",
    "preact/hooks": "/dashboard/vendor/preact-hooks.mjs",
    "htm": "/dashboard/vendor/htm.mjs"
  }
}
</script>
```

**Component pattern:**
```javascript
import { h, render } from 'preact'
import { useState, useEffect } from 'preact/hooks'
import { html } from '../lib/htm.js'

// html is htm bound to h — use like JSX:
function MyComponent() {
  const [count, setCount] = useState(0)
  return html`<button onClick=${() => setCount(count + 1)}>${count}</button>`
}
```

**REST API:** All endpoints at `/api/*` (built in previous workstreams).

**WebSocket:** `/api/ws` for real-time chat.

---

### Task 1: Vendor Dependencies + Project Structure

**Files:**
- Create: `dashboard/index.html`
- Create: `dashboard/vendor/` (vendored ES modules)
- Create: `dashboard/css/style.css`
- Create: `dashboard/lib/htm.js` (htm bound to preact's h)
- Create: `dashboard/js/app.js` (entry point)

**Step 1: Create directory structure**

```bash
mkdir -p dashboard/vendor dashboard/css dashboard/js dashboard/components dashboard/pages dashboard/lib
```

**Step 2: Download and vendor dependencies**

```bash
cd dashboard/vendor

# Preact core
curl -L "https://esm.sh/stable/preact@10.25.4/es2022/preact.mjs" -o preact.mjs

# Preact hooks
curl -L "https://esm.sh/stable/preact@10.25.4/es2022/hooks.js" -o preact-hooks.mjs

# HTM
curl -L "https://esm.sh/stable/htm@3.1.1/es2022/htm.mjs" -o htm.mjs
```

NOTE: The esm.sh URLs may have slightly different paths. If those don't work, try:
- `https://cdn.jsdelivr.net/npm/preact@10.25.4/dist/preact.module.js`
- `https://cdn.jsdelivr.net/npm/preact@10.25.4/hooks/dist/hooks.module.js`
- `https://cdn.jsdelivr.net/npm/htm@3.1.1/dist/htm.module.js`

The key requirement: each file must be a self-contained ES module with no external imports, OR any imports must reference other vendored files via the import map.

IMPORTANT: After downloading, verify each file is valid JS and doesn't import from external URLs. If it does, the import map will handle remapping `preact` -> vendored path. If the hooks module imports from `preact`, that's fine — the import map resolves it.

**Step 3: Create HTM binding helper**

```javascript
// dashboard/lib/htm.js
import { h } from 'preact'
import htm from 'htm'

export const html = htm.bind(h)
```

**Step 4: Create base CSS**

```css
/* dashboard/css/style.css */
:root {
  --bg: #09090b;
  --bg-card: #18181b;
  --bg-input: #27272a;
  --border: #3f3f46;
  --text: #fafafa;
  --text-muted: #a1a1aa;
  --primary: #3b82f6;
  --primary-hover: #2563eb;
  --success: #22c55e;
  --danger: #ef4444;
  --warning: #eab308;
  --radius: 8px;
  --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
  font-family: var(--font);
  background: var(--bg);
  color: var(--text);
  height: 100vh;
  overflow: hidden;
}

#app { height: 100%; }

/* Layout */
.layout { display: flex; height: 100%; }
.sidebar {
  width: 200px;
  border-right: 1px solid var(--border);
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.sidebar h1 { font-size: 18px; font-weight: 600; margin-bottom: 16px; padding: 0 8px; }
.sidebar a {
  display: block;
  padding: 8px 12px;
  border-radius: var(--radius);
  color: var(--text-muted);
  text-decoration: none;
  font-size: 14px;
  transition: background 0.15s, color 0.15s;
}
.sidebar a:hover { background: var(--bg-input); color: var(--text); }
.sidebar a.active { background: var(--bg-input); color: var(--text); font-weight: 500; }
.main { flex: 1; overflow: hidden; display: flex; flex-direction: column; }

/* Cards */
.card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px;
}
.card h3 { font-size: 14px; font-weight: 500; margin-bottom: 12px; color: var(--text-muted); }

/* Chat */
.chat-container { display: flex; flex-direction: column; height: 100%; }
.chat-header {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.chat-messages { flex: 1; overflow-y: auto; padding: 16px; }
.chat-input-bar {
  display: flex;
  gap: 8px;
  padding: 16px;
  border-top: 1px solid var(--border);
}
.chat-input-bar textarea {
  flex: 1;
  resize: none;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-input);
  color: var(--text);
  padding: 8px 12px;
  font-family: var(--font);
  font-size: 14px;
  outline: none;
}
.chat-input-bar textarea:focus { border-color: var(--primary); }
.chat-input-bar button {
  padding: 8px 16px;
  background: var(--primary);
  color: white;
  border: none;
  border-radius: var(--radius);
  font-size: 14px;
  cursor: pointer;
}
.chat-input-bar button:hover { background: var(--primary-hover); }
.chat-input-bar button:disabled { opacity: 0.5; cursor: not-allowed; }

.message { margin-bottom: 12px; display: flex; }
.message.user { justify-content: flex-end; }
.message.assistant { justify-content: flex-start; }
.message .bubble {
  max-width: 80%;
  padding: 8px 14px;
  border-radius: var(--radius);
  font-size: 14px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}
.message.user .bubble { background: var(--primary); color: white; }
.message.assistant .bubble { background: var(--bg-input); }
.message.thinking .bubble {
  background: var(--bg-input);
  color: var(--text-muted);
  animation: pulse 1.5s ease-in-out infinite;
}
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }

/* Status indicator */
.status-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  display: inline-block;
  margin-right: 4px;
}
.status-dot.connected { background: var(--success); }
.status-dot.disconnected { background: var(--danger); }

/* Dashboard grid */
.dashboard-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 16px;
  padding: 16px;
  overflow-y: auto;
}

/* Stats */
.stats-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.stat { text-align: center; }
.stat .value { font-size: 24px; font-weight: 600; }
.stat .label { font-size: 12px; color: var(--text-muted); margin-top: 4px; }

/* Item lists */
.item-list { list-style: none; }
.item-list li {
  padding: 8px 0;
  border-bottom: 1px solid var(--border);
  font-size: 13px;
}
.item-list li:last-child { border-bottom: none; }
.item-list .meta { font-size: 11px; color: var(--text-muted); margin-top: 2px; }

/* Badge */
.badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 500;
}
.badge.ok { background: #052e16; color: var(--success); }
.badge.warn { background: #422006; color: var(--warning); }
.badge.error { background: #450a0a; color: var(--danger); }

/* Settings */
.settings-content { padding: 16px; overflow-y: auto; }
.plugin-list { list-style: none; }
.plugin-list li {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 0;
  border-bottom: 1px solid var(--border);
  font-size: 14px;
}
```

**Step 5: Create index.html**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Odigos</title>
  <link rel="stylesheet" href="/dashboard/css/style.css">
  <script type="importmap">
  {
    "imports": {
      "preact": "/dashboard/vendor/preact.mjs",
      "preact/hooks": "/dashboard/vendor/preact-hooks.mjs",
      "htm": "/dashboard/vendor/htm.mjs"
    }
  }
  </script>
</head>
<body>
  <div id="app"></div>
  <script type="module" src="/dashboard/js/app.js"></script>
</body>
</html>
```

**Step 6: Create app entry point**

```javascript
// dashboard/js/app.js
import { render } from 'preact'
import { html } from '../lib/htm.js'
import { App } from '../components/App.js'

render(html`<${App} />`, document.getElementById('app'))
```

**Step 7: Create App shell component**

```javascript
// dashboard/components/App.js
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
```

**Step 8: Create placeholder pages**

```javascript
// dashboard/pages/ChatPage.js
import { html } from '../lib/htm.js'
export function ChatPage() {
  return html`<div class="chat-container"><div class="chat-header"><h2 style="font-size:18px;font-weight:600">Chat</h2></div><div class="chat-messages"><p style="text-align:center;color:var(--text-muted);margin-top:32px">Chat interface loading...</p></div></div>`
}
```

```javascript
// dashboard/pages/DashboardPage.js
import { html } from '../lib/htm.js'
export function DashboardPage() {
  return html`<div style="padding:16px"><h2 style="font-size:18px;font-weight:600;margin-bottom:16px">Dashboard</h2><p style="color:var(--text-muted)">Loading panels...</p></div>`
}
```

```javascript
// dashboard/pages/SettingsPage.js
import { html } from '../lib/htm.js'
export function SettingsPage() {
  return html`<div style="padding:16px"><h2 style="font-size:18px;font-weight:600;margin-bottom:16px">Settings</h2><p style="color:var(--text-muted)">Loading settings...</p></div>`
}
```

**Step 9: Commit**

```bash
git add dashboard/
git commit -m "feat(dashboard): scaffold vanilla JS dashboard with vendored Preact + HTM"
```

---

### Task 2: API Client + WebSocket Module

**Files:**
- Create: `dashboard/lib/api.js`
- Create: `dashboard/lib/ws.js`

**Step 1: Create API client**

```javascript
// dashboard/lib/api.js
const BASE = '/api'

async function fetchJSON(path, init) {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`)
  return res.json()
}

export const api = {
  conversations: {
    list: (limit = 20, offset = 0) => fetchJSON(`/conversations?limit=${limit}&offset=${offset}`),
    get: (id) => fetchJSON(`/conversations/${encodeURIComponent(id)}`),
    messages: (id) => fetchJSON(`/conversations/${encodeURIComponent(id)}/messages`),
  },
  goals: () => fetchJSON('/goals'),
  todos: () => fetchJSON('/todos'),
  reminders: () => fetchJSON('/reminders'),
  budget: () => fetchJSON('/budget'),
  metrics: () => fetchJSON('/metrics'),
  plugins: () => fetchJSON('/plugins'),
  memory: {
    entities: () => fetchJSON('/memory/entities'),
    search: (q) => fetchJSON(`/memory/search?q=${encodeURIComponent(q)}`),
  },
  sendMessage: (content, conversationId) =>
    fetchJSON('/message', {
      method: 'POST',
      body: JSON.stringify({ content, conversation_id: conversationId }),
    }),
}
```

**Step 2: Create WebSocket module**

```javascript
// dashboard/lib/ws.js

// Creates a managed WebSocket connection with auto-reconnect
export function createWsConnection(onMessage) {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  let ws = null
  let sessionId = null
  let conversationId = null
  let reconnectTimer = null

  function connect() {
    ws = new WebSocket(`${proto}//${location.host}/api/ws`)

    ws.onopen = () => {
      onMessage({ type: '_connected' })
    }

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      if (data.type === 'connected') {
        sessionId = data.session_id
        conversationId = data.conversation_id
      }
      onMessage(data)
    }

    ws.onclose = () => {
      onMessage({ type: '_disconnected' })
      reconnectTimer = setTimeout(connect, 3000)
    }

    ws.onerror = () => {
      ws.close()
    }
  }

  connect()

  return {
    send: (msg) => ws?.readyState === 1 && ws.send(JSON.stringify(msg)),
    sendChat: (content) => {
      const msg = { type: 'chat', content }
      if (conversationId) msg.conversation_id = conversationId
      ws?.readyState === 1 && ws.send(JSON.stringify(msg))
    },
    subscribe: (channels) => {
      ws?.readyState === 1 && ws.send(JSON.stringify({ type: 'subscribe', channels }))
    },
    getSessionId: () => sessionId,
    getConversationId: () => conversationId,
    close: () => {
      clearTimeout(reconnectTimer)
      ws?.close()
    },
  }
}
```

**Step 3: Commit**

```bash
git add dashboard/lib/
git commit -m "feat(dashboard): add API client and WebSocket module"
```

---

### Task 3: Chat Interface

**Files:**
- Update: `dashboard/pages/ChatPage.js`

Full chat page implementation with WebSocket-powered real-time messaging.

```javascript
// dashboard/pages/ChatPage.js
import { useState, useEffect, useRef, useCallback } from 'preact/hooks'
import { html } from '../lib/htm.js'
import { createWsConnection } from '../lib/ws.js'

export function ChatPage() {
  const [messages, setMessages] = useState([])
  const [waiting, setWaiting] = useState(false)
  const [connected, setConnected] = useState(false)
  const [input, setInput] = useState('')
  const scrollRef = useRef(null)
  const wsRef = useRef(null)

  useEffect(() => {
    const ws = createWsConnection((data) => {
      if (data.type === '_connected') setConnected(true)
      if (data.type === '_disconnected') setConnected(false)
      if (data.type === 'chat' || data.type === 'chat_response') {
        setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'assistant', content: data.content }])
        setWaiting(false)
      }
    })
    wsRef.current = ws
    return () => ws.close()
  }, [])

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, waiting])

  const handleSend = useCallback(() => {
    const text = input.trim()
    if (!text || !connected) return
    setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'user', content: text }])
    setInput('')
    setWaiting(true)
    wsRef.current?.sendChat(text)
  }, [input, connected])

  const handleKeyDown = useCallback((e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }, [handleSend])

  return html`
    <div class="chat-container">
      <div class="chat-header">
        <h2 style="font-size:18px;font-weight:600">Chat</h2>
        <span style="font-size:12px;display:flex;align-items:center">
          <span class="status-dot ${connected ? 'connected' : 'disconnected'}"></span>
          ${connected ? 'Connected' : 'Disconnected'}
        </span>
      </div>

      <div class="chat-messages" ref=${scrollRef}>
        ${messages.length === 0 && !waiting && html`
          <p style="text-align:center;color:var(--text-muted);margin-top:32px">
            Start a conversation...
          </p>
        `}
        ${messages.map(msg => html`
          <div class="message ${msg.role}" key=${msg.id}>
            <div class="bubble">${msg.content}</div>
          </div>
        `)}
        ${waiting && html`
          <div class="message thinking">
            <div class="bubble">Thinking...</div>
          </div>
        `}
      </div>

      <div class="chat-input-bar">
        <textarea
          value=${input}
          onInput=${(e) => setInput(e.target.value)}
          onKeyDown=${handleKeyDown}
          placeholder="Type a message..."
          disabled=${!connected}
          rows="1"
        />
        <button onClick=${handleSend} disabled=${!connected || !input.trim()}>
          Send
        </button>
      </div>
    </div>
  `
}
```

**Commit:**
```bash
git add dashboard/pages/ChatPage.js
git commit -m "feat(dashboard): implement chat interface with WebSocket"
```

---

### Task 4: Dashboard Monitoring Page

**Files:**
- Update: `dashboard/pages/DashboardPage.js`

Dashboard with 4 panels fetching from REST API on mount.

```javascript
// dashboard/pages/DashboardPage.js
import { useState, useEffect } from 'preact/hooks'
import { html } from '../lib/htm.js'
import { api } from '../lib/api.js'

function MetricsPanel({ metrics }) {
  return html`
    <div class="card">
      <h3>System Metrics</h3>
      <div class="stats-grid">
        <div class="stat">
          <div class="value">${metrics?.conversation_count ?? '—'}</div>
          <div class="label">Conversations</div>
        </div>
        <div class="stat">
          <div class="value">${metrics?.message_count ?? '—'}</div>
          <div class="label">Messages</div>
        </div>
        <div class="stat">
          <div class="value">$${metrics?.total_cost_usd?.toFixed(2) ?? '—'}</div>
          <div class="label">Total Cost</div>
        </div>
      </div>
    </div>
  `
}

function BudgetPanel({ budget }) {
  if (!budget) return html`<div class="card"><h3>Budget</h3><p style="color:var(--text-muted)">Loading...</p></div>`
  const dailyPct = budget.daily_limit ? Math.min(100, (budget.daily_spend / budget.daily_limit) * 100) : 0
  const monthlyPct = budget.monthly_limit ? Math.min(100, (budget.monthly_spend / budget.monthly_limit) * 100) : 0

  return html`
    <div class="card">
      <h3>Budget</h3>
      <div style="margin-bottom:12px">
        <div style="display:flex;justify-content:space-between;font-size:13px;margin-bottom:4px">
          <span>Daily</span>
          <span>$${budget.daily_spend.toFixed(2)} / $${budget.daily_limit.toFixed(2)}</span>
        </div>
        <div style="height:6px;background:var(--bg-input);border-radius:3px;overflow:hidden">
          <div style="height:100%;width:${dailyPct}%;background:${dailyPct > 80 ? 'var(--danger)' : 'var(--primary)'};border-radius:3px;transition:width 0.3s"></div>
        </div>
      </div>
      <div>
        <div style="display:flex;justify-content:space-between;font-size:13px;margin-bottom:4px">
          <span>Monthly</span>
          <span>$${budget.monthly_spend.toFixed(2)} / $${budget.monthly_limit.toFixed(2)}</span>
        </div>
        <div style="height:6px;background:var(--bg-input);border-radius:3px;overflow:hidden">
          <div style="height:100%;width:${monthlyPct}%;background:${monthlyPct > 80 ? 'var(--danger)' : 'var(--primary)'};border-radius:3px;transition:width 0.3s"></div>
        </div>
      </div>
      <div style="margin-top:8px">
        <span class="badge ${budget.within_budget ? 'ok' : 'error'}">
          ${budget.within_budget ? 'Within budget' : 'Over budget'}
        </span>
      </div>
    </div>
  `
}

function GoalsPanel({ goals, todos, reminders }) {
  return html`
    <div class="card">
      <h3>Goals (${goals?.length ?? 0})</h3>
      ${goals?.length ? html`
        <ul class="item-list">
          ${goals.map(g => html`
            <li key=${g.id}>
              ${g.description}
              ${g.progress_note && html`<div class="meta">${g.progress_note}</div>`}
            </li>
          `)}
        </ul>
      ` : html`<p style="color:var(--text-muted);font-size:13px">No active goals</p>`}

      <h3 style="margin-top:16px">Todos (${todos?.length ?? 0})</h3>
      ${todos?.length ? html`
        <ul class="item-list">
          ${todos.slice(0, 5).map(t => html`<li key=${t.id}>${t.description}</li>`)}
        </ul>
      ` : html`<p style="color:var(--text-muted);font-size:13px">No pending todos</p>`}

      <h3 style="margin-top:16px">Reminders (${reminders?.length ?? 0})</h3>
      ${reminders?.length ? html`
        <ul class="item-list">
          ${reminders.slice(0, 5).map(r => html`
            <li key=${r.id}>
              ${r.description}
              ${r.recurrence && html`<div class="meta">recurring: ${r.recurrence}</div>`}
            </li>
          `)}
        </ul>
      ` : html`<p style="color:var(--text-muted);font-size:13px">No pending reminders</p>`}
    </div>
  `
}

export function DashboardPage() {
  const [metrics, setMetrics] = useState(null)
  const [budget, setBudget] = useState(null)
  const [goals, setGoals] = useState(null)
  const [todos, setTodos] = useState(null)
  const [reminders, setReminders] = useState(null)

  useEffect(() => {
    api.metrics().then(setMetrics).catch(() => {})
    api.budget().then(setBudget).catch(() => {})
    api.goals().then(d => setGoals(d.goals)).catch(() => {})
    api.todos().then(d => setTodos(d.todos)).catch(() => {})
    api.reminders().then(d => setReminders(d.reminders)).catch(() => {})
  }, [])

  return html`
    <div>
      <div style="padding:16px 16px 0">
        <h2 style="font-size:18px;font-weight:600">Dashboard</h2>
      </div>
      <div class="dashboard-grid">
        <${MetricsPanel} metrics=${metrics} />
        <${BudgetPanel} budget=${budget} />
        <${GoalsPanel} goals=${goals} todos=${todos} reminders=${reminders} />
      </div>
    </div>
  `
}
```

**Commit:**
```bash
git add dashboard/pages/DashboardPage.js
git commit -m "feat(dashboard): add monitoring panels — metrics, budget, goals"
```

---

### Task 5: Settings Page

**Files:**
- Update: `dashboard/pages/SettingsPage.js`

```javascript
// dashboard/pages/SettingsPage.js
import { useState, useEffect } from 'preact/hooks'
import { html } from '../lib/htm.js'
import { api } from '../lib/api.js'

export function SettingsPage() {
  const [plugins, setPlugins] = useState(null)

  useEffect(() => {
    api.plugins().then(d => setPlugins(d.plugins)).catch(() => {})
  }, [])

  return html`
    <div class="settings-content">
      <h2 style="font-size:18px;font-weight:600;margin-bottom:16px">Settings</h2>

      <div class="card" style="margin-bottom:16px">
        <h3>Plugins</h3>
        ${plugins === null ? html`<p style="color:var(--text-muted);font-size:13px">Loading...</p>` :
          plugins.length === 0 ? html`<p style="color:var(--text-muted);font-size:13px">No plugins loaded</p>` : html`
          <ul class="plugin-list">
            ${plugins.map(p => html`
              <li key=${p.name}>
                <span>${p.name}</span>
                <span class="badge ok">${p.status}</span>
              </li>
            `)}
          </ul>
        `}
      </div>
    </div>
  `
}
```

**Commit:**
```bash
git add dashboard/pages/SettingsPage.js
git commit -m "feat(dashboard): add settings page with plugins panel"
```

---

### Task 6: FastAPI Static File Serving

**Files:**
- Modify: `odigos/main.py` — serve dashboard directory with SPA catch-all
- Test: `tests/test_dashboard_serving.py`

**Step 1: Write the failing test**

```python
# tests/test_dashboard_serving.py
import os
import pytest
from httpx import ASGITransport, AsyncClient


class TestDashboardServing:
    async def test_index_served(self, tmp_path):
        # Create fake dashboard structure
        (tmp_path / "index.html").write_text("<html><body>Odigos Dashboard</body></html>")
        css_dir = tmp_path / "css"
        css_dir.mkdir()
        (css_dir / "style.css").write_text("body { color: red; }")

        from odigos.main import app
        from odigos.dashboard import mount_dashboard
        mount_dashboard(app, str(tmp_path))

        from unittest.mock import AsyncMock, MagicMock
        app.state.settings = type("S", (), {"api_key": ""})()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            # Root serves index.html
            resp = await c.get("/")
            assert resp.status_code == 200
            assert "Odigos Dashboard" in resp.text

            # Static files served
            resp = await c.get("/dashboard/css/style.css")
            assert resp.status_code == 200

            # Unknown paths fall back to index.html (SPA routing)
            resp = await c.get("/chat/some-conversation")
            assert resp.status_code == 200
            assert "Odigos Dashboard" in resp.text
```

**Step 2: Create `odigos/dashboard.py`**

```python
# odigos/dashboard.py
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

DEFAULT_DASHBOARD_DIR = os.path.join(os.path.dirname(__file__), "..", "dashboard")


def mount_dashboard(app: FastAPI, dashboard_dir: str | None = None) -> None:
    dist = dashboard_dir or DEFAULT_DASHBOARD_DIR
    index_html = os.path.join(dist, "index.html")

    if not os.path.isfile(index_html):
        return

    # Mount static subdirectories
    for subdir in ("vendor", "css", "js", "lib", "components", "pages"):
        subdir_path = os.path.join(dist, subdir)
        if os.path.isdir(subdir_path):
            app.mount(f"/dashboard/{subdir}", StaticFiles(directory=subdir_path), name=f"dashboard_{subdir}")

    # Catch-all: serve index.html for SPA routing
    @app.get("/{path:path}")
    async def serve_spa(path: str):
        file_path = os.path.join(dist, path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(index_html)
```

**Step 3: Wire into main.py**

Add after all `app.include_router(...)` calls:
```python
from odigos.dashboard import mount_dashboard
mount_dashboard(app)
```

IMPORTANT: This MUST be the last route registration since the catch-all would shadow anything after it.

**Step 4: Run tests**

```bash
pytest tests/test_dashboard_serving.py -v
pytest tests/ -x -q
```

**Step 5: Commit**

```bash
git add odigos/dashboard.py odigos/main.py tests/test_dashboard_serving.py
git commit -m "feat(dashboard): serve static dashboard files from FastAPI"
```
