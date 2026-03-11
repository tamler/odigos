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
