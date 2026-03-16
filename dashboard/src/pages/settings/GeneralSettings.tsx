import { useEffect, useState, useCallback } from 'react'
import { useTheme } from 'next-themes'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { get, post } from '@/lib/api'
import { toast } from 'sonner'
import { Sun, Moon, Monitor, AlertCircle } from 'lucide-react'

const PROVIDERS = [
  { id: 'openrouter', name: 'OpenRouter', url: 'https://openrouter.ai/api/v1', model: 'anthropic/claude-sonnet-4', fallback: 'google/gemini-2.0-flash-001' },
  { id: 'openai', name: 'OpenAI', url: 'https://api.openai.com/v1', model: 'gpt-4o', fallback: 'gpt-4o-mini' },
  { id: 'ollama', name: 'Ollama', url: 'http://host.docker.internal:11434/v1', model: 'llama3.2', fallback: 'llama3.2' },
  { id: 'lmstudio', name: 'LM Studio', url: 'http://host.docker.internal:1234/v1', model: 'default', fallback: 'default' },
  { id: 'custom', name: 'Custom', url: '', model: '', fallback: '' },
]

interface SettingsData {
  llm_api_key: string
  api_key: string
  llm: { base_url: string; default_model: string; fallback_model: string; background_model: string; max_tokens: number; temperature: number }
  agent: { name: string; max_tool_turns: number; run_timeout_seconds: number }
  budget: { daily_limit_usd: number; monthly_limit_usd: number; warn_threshold: number }
  heartbeat: { interval_seconds: number; max_todos_per_tick: number; idle_think_interval: number }
  sandbox: { timeout_seconds: number; max_memory_mb: number; allow_network: boolean }
  mesh: { enabled: boolean }
  feed: { enabled: boolean; public: boolean; max_entries: number }
  templates: { repo_url: string; cache_ttl_days: number }
}

interface Props {
  needsSetup?: boolean
  active?: boolean
}

function SectionCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border/40 bg-card">
      <div className="px-5 py-3 border-b border-border/40">
        <h2 className="text-sm font-medium">{title}</h2>
      </div>
      <div className="px-5 py-4 space-y-4">
        {children}
      </div>
    </div>
  )
}

export default function GeneralSettings({ needsSetup, active }: Props) {
  const [settings, setSettings] = useState<SettingsData | null>(null)
  const [saving, setSaving] = useState(false)
  const [selectedProvider, setSelectedProvider] = useState<string | null>(null)
  const { theme, setTheme } = useTheme()

  const loadSettings = useCallback(() => {
    get<SettingsData>('/api/settings')
      .then(setSettings)
      .catch(() => {})
  }, [])

  useEffect(() => { loadSettings() }, [loadSettings])

  useEffect(() => { if (active) loadSettings() }, [active])

  function selectProvider(id: string) {
    const p = PROVIDERS.find((p) => p.id === id)
    if (!p || !settings) return
    setSelectedProvider(id)
    setSettings({
      ...settings,
      llm: { ...settings.llm, base_url: p.url, default_model: p.model, fallback_model: p.fallback },
    })
  }

  function update(section: string, field: string, value: string | number | boolean) {
    if (!settings) return
    setSettings({ ...settings, [section]: { ...(settings as any)[section], [field]: value } })
  }

  async function save() {
    if (!settings) return
    setSaving(true)
    try {
      await post('/api/settings', settings)
      toast.success('Settings saved')
      if (needsSetup) {
        window.location.href = '/'
      }
    } catch {
      toast.error('Failed to save settings')
    } finally {
      setSaving(false)
    }
  }

  if (!settings) {
    return <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">Loading...</div>
  }

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 py-4 sm:py-6 space-y-5">
      {/* Save bar */}
      <div className="flex items-center justify-end">
        <Button onClick={save} disabled={saving} size="sm">
          {saving ? 'Saving...' : needsSetup ? 'Save & Start' : 'Save'}
        </Button>
      </div>

      {needsSetup && (
        <Alert>
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>Configure your LLM provider to get started.</AlertDescription>
        </Alert>
      )}

      {/* Appearance */}
      <SectionCard title="Appearance">
        <div className="flex gap-2">
          {[
            { value: 'light', icon: Sun, label: 'Light' },
            { value: 'dark', icon: Moon, label: 'Dark' },
            { value: 'system', icon: Monitor, label: 'System' },
          ].map(({ value, icon: Icon, label }) => (
            <Button
              key={value}
              variant={theme === value ? 'default' : 'outline'}
              size="sm"
              onClick={() => setTheme(value)}
              className="gap-2"
            >
              <Icon className="h-4 w-4" /> {label}
            </Button>
          ))}
        </div>
      </SectionCard>

      {/* LLM Provider */}
      <SectionCard title="LLM Provider">
        <div className="flex flex-wrap gap-2">
          {PROVIDERS.map((p) => (
            <Button
              key={p.id}
              variant={selectedProvider === p.id ? 'default' : 'outline'}
              size="sm"
              onClick={() => selectProvider(p.id)}
            >
              {p.name}
            </Button>
          ))}
        </div>
        <div className="grid gap-4">
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">Base URL</Label>
            <Input value={settings.llm.base_url} onChange={(e) => update('llm', 'base_url', e.target.value)} className="bg-muted/50 border-border/40" />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">API Key</Label>
            <Input type="password" placeholder="****" onChange={(e) => setSettings(s => s ? { ...s, llm_api_key: e.target.value } : s)} className="bg-muted/50 border-border/40" />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">Default Model</Label>
            <Input value={settings.llm.default_model} onChange={(e) => update('llm', 'default_model', e.target.value)} className="bg-muted/50 border-border/40" />
            <p className="text-xs text-muted-foreground">Used for chat, evaluation, strategy, and all primary tasks.</p>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Fallback Model</Label>
              <Input value={settings.llm.fallback_model} onChange={(e) => update('llm', 'fallback_model', e.target.value)} className="bg-muted/50 border-border/40" />
              <p className="text-xs text-muted-foreground">Used when default model fails.</p>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Background Model</Label>
              <Input value={settings.llm.background_model} onChange={(e) => update('llm', 'background_model', e.target.value)} placeholder={settings.llm.default_model} className="bg-muted/50 border-border/40" />
              <p className="text-xs text-muted-foreground">Optional cheaper model for idle thinking. Defaults to default model.</p>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Max Tokens</Label>
              <Input type="number" value={settings.llm.max_tokens} onChange={(e) => update('llm', 'max_tokens', parseInt(e.target.value))} className="bg-muted/50 border-border/40" />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Temperature</Label>
              <Input type="number" step="0.1" value={settings.llm.temperature} onChange={(e) => update('llm', 'temperature', parseFloat(e.target.value))} className="bg-muted/50 border-border/40" />
            </div>
          </div>
        </div>
      </SectionCard>

      {/* Agent */}
      <SectionCard title="Agent">
        <div className="space-y-1.5">
          <Label className="text-xs text-muted-foreground">Name</Label>
          <Input value={settings.agent.name} onChange={(e) => update('agent', 'name', e.target.value)} className="bg-muted/50 border-border/40" />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">Max Tool Turns</Label>
            <Input type="number" value={settings.agent.max_tool_turns} onChange={(e) => update('agent', 'max_tool_turns', parseInt(e.target.value))} className="bg-muted/50 border-border/40" />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">Run Timeout (s)</Label>
            <Input type="number" value={settings.agent.run_timeout_seconds} onChange={(e) => update('agent', 'run_timeout_seconds', parseInt(e.target.value))} className="bg-muted/50 border-border/40" />
          </div>
        </div>
      </SectionCard>

      {/* Budget */}
      <SectionCard title="Budget">
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">Daily Limit (USD)</Label>
            <Input type="number" step="0.5" value={settings.budget.daily_limit_usd} onChange={(e) => update('budget', 'daily_limit_usd', parseFloat(e.target.value))} className="bg-muted/50 border-border/40" />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">Monthly Limit (USD)</Label>
            <Input type="number" step="1" value={settings.budget.monthly_limit_usd} onChange={(e) => update('budget', 'monthly_limit_usd', parseFloat(e.target.value))} className="bg-muted/50 border-border/40" />
          </div>
        </div>
      </SectionCard>

      {/* Security */}
      <SectionCard title="Security">
        <div className="space-y-1.5">
          <Label className="text-xs text-muted-foreground">Dashboard API Key</Label>
          <Input type="password" placeholder="****" onChange={(e) => setSettings(s => s ? { ...s, api_key: e.target.value } : s)} className="bg-muted/50 border-border/40" />
          <p className="text-xs text-muted-foreground">Used to authenticate browser sessions. Set a persistent key to survive container restarts.</p>
        </div>
      </SectionCard>

      {/* Mesh Networking */}
      <SectionCard title="Mesh Networking">
        <div className="flex items-center justify-between">
          <div className="space-y-0.5">
            <Label className="text-sm">Agent Mesh</Label>
            <p className="text-xs text-muted-foreground">Enable peer-to-peer agent communication over the mesh. Disable for standalone / hermit mode.</p>
          </div>
          <Button
            variant={settings.mesh.enabled ? 'default' : 'outline'}
            size="sm"
            onClick={() => update('mesh', 'enabled', !settings.mesh.enabled)}
          >
            {settings.mesh.enabled ? 'Enabled' : 'Disabled'}
          </Button>
        </div>
      </SectionCard>

      {/* Feed */}
      <SectionCard title="Feed">
        <div className="flex items-center justify-between">
          <div className="space-y-0.5">
            <Label className="text-sm">Feed Publisher</Label>
            <p className="text-xs text-muted-foreground">Enable the RSS feed endpoint so other agents can subscribe to your updates.</p>
          </div>
          <Button
            variant={settings.feed.enabled ? 'default' : 'outline'}
            size="sm"
            onClick={() => update('feed', 'enabled', !settings.feed.enabled)}
          >
            {settings.feed.enabled ? 'Enabled' : 'Disabled'}
          </Button>
        </div>
        <div className="flex items-center justify-between">
          <div className="space-y-0.5">
            <Label className="text-sm">Public Feed</Label>
            <p className="text-xs text-muted-foreground">Allow anyone to read your feed without a subscribe card.</p>
          </div>
          <Button
            variant={settings.feed.public ? 'default' : 'outline'}
            size="sm"
            onClick={() => update('feed', 'public', !settings.feed.public)}
          >
            {settings.feed.public ? 'Public' : 'Private'}
          </Button>
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs text-muted-foreground">Max Entries</Label>
          <Input type="number" value={settings.feed.max_entries} onChange={(e) => update('feed', 'max_entries', parseInt(e.target.value))} className="bg-muted/50 border-border/40 w-24" />
        </div>
      </SectionCard>

      {/* Agent Templates */}
      <SectionCard title="Agent Templates">
        <div className="space-y-1.5">
          <Label className="text-xs text-muted-foreground">Template Repository URL</Label>
          <Input value={settings.templates.repo_url} onChange={(e) => update('templates', 'repo_url', e.target.value)} placeholder="https://github.com/msitarzewski/agency-agents" className="bg-muted/50 border-border/40" />
          <p className="text-xs text-muted-foreground">GitHub repository of agent personality templates. The agent uses these to build specialized identities when spawning or adopting roles.</p>
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs text-muted-foreground">Cache TTL (days)</Label>
          <Input type="number" value={settings.templates.cache_ttl_days} onChange={(e) => update('templates', 'cache_ttl_days', parseInt(e.target.value))} className="bg-muted/50 border-border/40 w-24" />
          <p className="text-xs text-muted-foreground">How long to cache templates before re-fetching from GitHub.</p>
        </div>
      </SectionCard>

      {/* Advanced */}
      <SectionCard title="Advanced">
        <div className="grid grid-cols-3 gap-4">
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">Heartbeat (s)</Label>
            <Input type="number" value={settings.heartbeat.interval_seconds} onChange={(e) => update('heartbeat', 'interval_seconds', parseInt(e.target.value))} className="bg-muted/50 border-border/40" />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">Sandbox Timeout (s)</Label>
            <Input type="number" value={settings.sandbox.timeout_seconds} onChange={(e) => update('sandbox', 'timeout_seconds', parseInt(e.target.value))} className="bg-muted/50 border-border/40" />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">Sandbox Memory (MB)</Label>
            <Input type="number" value={settings.sandbox.max_memory_mb} onChange={(e) => update('sandbox', 'max_memory_mb', parseInt(e.target.value))} className="bg-muted/50 border-border/40" />
          </div>
        </div>
      </SectionCard>

      <div className="h-4" />
    </div>
  )
}
