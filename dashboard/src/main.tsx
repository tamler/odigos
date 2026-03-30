import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { ThemeProvider } from './components/ThemeProvider'
import App from './App'
import './index.css'

// Global CSRF protection: intercept ALL fetch calls and add the header.
// This covers api.ts helpers, raw fetch in voice/push/upload, and any
// future code. No more per-call header sprinkling.
const _originalFetch = window.fetch
window.fetch = function (input: RequestInfo | URL, init?: RequestInit) {
  const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
  const isSameOrigin = url.startsWith('/') || url.startsWith(window.location.origin)
  const method = init?.method?.toUpperCase() || 'GET'
  const needsCsrf = isSameOrigin && method !== 'GET' && method !== 'HEAD'

  if (needsCsrf) {
    const headers = new Headers(init?.headers)
    if (!headers.has('X-Requested-With')) {
      headers.set('X-Requested-With', 'XMLHttpRequest')
    }
    return _originalFetch(input, { ...init, headers })
  }
  return _originalFetch(input, init)
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider>
      <App />
    </ThemeProvider>
  </StrictMode>,
)

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
  });
}
