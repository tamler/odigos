import { useState, useEffect, useCallback } from 'react'
import { get } from '@/lib/api'
import { Activity, Cpu, Brain, MessageSquare, Wrench, Zap } from 'lucide-react'

interface AgentState {
  agent: {
    name: string
    role: string
    uptime: string
    uptime_seconds: number
    active_conversations: number
  }
  budget: {
    daily_spend: number
    daily_limit: number
    monthly_spend: number
    monthly_limit: number
    within_budget: boolean
    warning: boolean
  }
  memory: {
    total: number
    recent_24h: number
  }
  conversations: {
    active: number
    total: number
    recent_messages_1h: number
  }
  tools: string[]
  skills: { name: string; description: string; complexity: string; enabled: boolean }[]
  plugins: { name: string; status: string }[]
  evolution: {
    cycle_count: number
    evaluation_count: number
    recent_avg_score: number | null
    active_trial: { id: string; hypothesis: string; target: string; status: string } | null
  }
  heartbeat: {
    interval: number | null
    paused: boolean | null
    uptime: string
  }
  cron: { total: number; enabled: number } | null
  system: {
    python_version: string
    platform: string
    pid: number
  }
}

function ProgressBar({ value, max, color }: { value: number; max: number; color: string }) {
  const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0
  return (
    <div className="w-full bg-muted rounded-full h-2.5">
      <div className={`h-2.5 rounded-full ${color}`} style={{ width: `${pct}%` }} />
    </div>
  )
}

function budgetColor(spend: number, limit: number): string {
  if (limit <= 0) return 'bg-green-500'
  const ratio = spend / limit
  if (ratio >= 1) return 'bg-red-500'
  if (ratio >= 0.8) return 'bg-yellow-500'
  return 'bg-green-500'
}

function Section({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border/40 p-5">
      <div className="flex items-center gap-2 mb-4">
        {icon}
        <h3 className="text-sm font-semibold text-foreground">{title}</h3>
      </div>
      {children}
    </div>
  )
}

function Label({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between items-center py-1">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className="text-sm font-medium text-foreground">{value}</span>
    </div>
  )
}

export default function StatePage() {
  const [state, setState] = useState<AgentState | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null)

  const refresh = useCallback(() => {
    get<AgentState>('/api/state')
      .then((data) => {
        setState(data)
        setError(null)
        setLastRefresh(new Date())
      })
      .catch((err) => setError(err.message))
  }, [])

  useEffect(() => {
    refresh()
    const timer = setInterval(refresh, 10_000)
    return () => clearInterval(timer)
  }, [refresh])

  if (error) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <p className="text-destructive text-sm">Failed to load state: {error}</p>
      </div>
    )
  }

  if (!state) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <p className="text-muted-foreground text-sm">Loading agent state...</p>
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 py-6 sm:py-8 space-y-6">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-lg font-semibold text-foreground">Agent State Inspector</h2>
          {lastRefresh && (
            <span className="text-xs text-muted-foreground">
              Updated {lastRefresh.toLocaleTimeString()}
            </span>
          )}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Agent */}
          <Section title="Agent" icon={<Cpu className="h-4 w-4 text-blue-500" />}>
            <Label label="Name" value={state.agent.name} />
            <Label label="Role" value={state.agent.role} />
            <Label label="Uptime" value={state.agent.uptime} />
            <Label label="Active conversations" value={state.agent.active_conversations} />
          </Section>

          {/* Budget */}
          <Section title="Budget" icon={<Activity className="h-4 w-4 text-green-500" />}>
            <div className="space-y-3">
              <div>
                <div className="flex justify-between text-xs text-muted-foreground mb-1">
                  <span>Daily: ${state.budget.daily_spend.toFixed(4)}</span>
                  <span>${state.budget.daily_limit.toFixed(2)} limit</span>
                </div>
                <ProgressBar
                  value={state.budget.daily_spend}
                  max={state.budget.daily_limit}
                  color={budgetColor(state.budget.daily_spend, state.budget.daily_limit)}
                />
              </div>
              <div>
                <div className="flex justify-between text-xs text-muted-foreground mb-1">
                  <span>Monthly: ${state.budget.monthly_spend.toFixed(4)}</span>
                  <span>${state.budget.monthly_limit.toFixed(2)} limit</span>
                </div>
                <ProgressBar
                  value={state.budget.monthly_spend}
                  max={state.budget.monthly_limit}
                  color={budgetColor(state.budget.monthly_spend, state.budget.monthly_limit)}
                />
              </div>
              {!state.budget.within_budget && (
                <p className="text-xs text-red-500 font-medium">Budget exceeded</p>
              )}
              {state.budget.warning && (
                <p className="text-xs text-yellow-500 font-medium">Approaching budget limit</p>
              )}
            </div>
          </Section>

          {/* Activity */}
          <Section title="Activity" icon={<MessageSquare className="h-4 w-4 text-purple-500" />}>
            <Label label="Total conversations" value={state.conversations.total} />
            <Label label="Active (last hour)" value={state.conversations.active} />
            <Label label="Messages (last hour)" value={state.conversations.recent_messages_1h} />
            <Label label="Memories stored" value={state.memory.total} />
            <Label label="Memories (24h)" value={state.memory.recent_24h} />
          </Section>

          {/* Evolution */}
          <Section title="Evolution" icon={<Zap className="h-4 w-4 text-yellow-500" />}>
            <Label label="Trial cycles" value={state.evolution.cycle_count} />
            <Label label="Evaluations" value={state.evolution.evaluation_count} />
            <Label
              label="Avg score (recent)"
              value={state.evolution.recent_avg_score !== null ? state.evolution.recent_avg_score.toFixed(2) : '--'}
            />
            {state.evolution.active_trial ? (
              <div className="mt-2 p-2 rounded bg-accent/30 text-xs">
                <p className="font-medium text-foreground">Active trial</p>
                <p className="text-muted-foreground mt-1">{state.evolution.active_trial.hypothesis}</p>
                <p className="text-muted-foreground">Target: {state.evolution.active_trial.target}</p>
              </div>
            ) : (
              <p className="text-xs text-muted-foreground mt-2">No active trial</p>
            )}
          </Section>

          {/* Tools & Skills */}
          <Section title="Tools & Skills" icon={<Wrench className="h-4 w-4 text-orange-500" />}>
            <div className="space-y-3">
              <div>
                <p className="text-xs text-muted-foreground mb-1">Tools ({state.tools.length})</p>
                <div className="flex flex-wrap gap-1">
                  {state.tools.map((t) => (
                    <span key={t} className="inline-block px-2 py-0.5 bg-accent/50 text-xs rounded text-foreground">
                      {t}
                    </span>
                  ))}
                </div>
              </div>
              <div>
                <p className="text-xs text-muted-foreground mb-1">Skills ({state.skills.length})</p>
                <div className="flex flex-wrap gap-1">
                  {state.skills.map((s) => (
                    <span
                      key={s.name}
                      className={`inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded ${
                        s.enabled ? 'bg-green-500/10 text-green-600' : 'bg-muted text-muted-foreground'
                      }`}
                    >
                      <span className={`w-1.5 h-1.5 rounded-full ${s.enabled ? 'bg-green-500' : 'bg-muted-foreground'}`} />
                      {s.name}
                    </span>
                  ))}
                </div>
              </div>
              {state.plugins.length > 0 && (
                <div>
                  <p className="text-xs text-muted-foreground mb-1">Plugins ({state.plugins.length})</p>
                  <div className="flex flex-wrap gap-1">
                    {state.plugins.map((p) => (
                      <span
                        key={p.name}
                        className={`inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded ${
                          p.status === 'active' ? 'bg-green-500/10 text-green-600' : 'bg-red-500/10 text-red-600'
                        }`}
                      >
                        <span className={`w-1.5 h-1.5 rounded-full ${p.status === 'active' ? 'bg-green-500' : 'bg-red-500'}`} />
                        {p.name}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </Section>

          {/* System */}
          <Section title="System" icon={<Brain className="h-4 w-4 text-cyan-500" />}>
            <Label label="PID" value={state.system.pid} />
            <Label label="Platform" value={state.system.platform} />
            <Label label="Python" value={state.system.python_version.split(' ')[0]} />
            <Label
              label="Heartbeat"
              value={
                state.heartbeat.interval !== null
                  ? `${state.heartbeat.interval}s${state.heartbeat.paused ? ' (paused)' : ''}`
                  : '--'
              }
            />
            {state.cron && (
              <Label label="Cron entries" value={`${state.cron.enabled}/${state.cron.total} enabled`} />
            )}
          </Section>
        </div>
      </div>
    </div>
  )
}
