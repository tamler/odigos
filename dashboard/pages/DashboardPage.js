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
      <h3>Goals ($${goals?.length ?? 0})</h3>
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

      <h3 style="margin-top:16px">Todos ($${todos?.length ?? 0})</h3>
      ${todos?.length ? html`
        <ul class="item-list">
          ${todos.slice(0, 5).map(t => html`<li key=${t.id}>${t.description}</li>`)}
        </ul>
      ` : html`<p style="color:var(--text-muted);font-size:13px">No pending todos</p>`}

      <h3 style="margin-top:16px">Reminders ($${reminders?.length ?? 0})</h3>
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
