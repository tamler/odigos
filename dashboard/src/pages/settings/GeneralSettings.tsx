import { useEffect, useState, useCallback } from 'react'
import { useTheme } from 'next-themes'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { get, post } from '@/lib/api'
import { toast } from 'sonner'
import { Sun, Moon, Monitor, Plus, Trash2 } from 'lucide-react'

interface ProviderEntry {
  base_url: string
  api_key: string // "****" when masked, empty string to delete, new value to replace
}

interface ModelEntry {
  provider: string
  id: string
  cost_in_per_mtok: number
  cost_out_per_mtok: number
  vision: boolean
  context_window: number
  notes?: string
}

interface LLMRouting {
  fast: string
  smart: string
  background: string
  fallback: string
  max_tokens: number
  temperature: number
  request_timeout_seconds: number
  connect_timeout_seconds: number
  auto_route: boolean
}

interface SettingsData {
  api_key: string
  providers: Record<string, ProviderEntry>
  models: Record<string, ModelEntry>
  llm: LLMRouting
  agent: { name: string; profile?: string; max_tool_turns: number; run_timeout_seconds: number }
  budget: { daily_limit_usd: number; monthly_limit_usd: number; warn_threshold: number }
  heartbeat: { interval_seconds: number; max_todos_per_tick: number; idle_think_interval: number }
  sandbox: { timeout_seconds: number; max_memory_mb: number; allow_network: boolean }
  mesh: { enabled: boolean }
  feed: { enabled: boolean; public: boolean; max_entries: number }
  templates: { repo_url: string; cache_ttl_days: number }
}

interface Profile {
  id: string
  name: string
  description: string
}

interface Props {
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

export default function GeneralSettings({ active }: Props) {
  const [settings, setSettings] = useState<SettingsData | null>(null)
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [saving, setSaving] = useState(false)
  const [applyingProfile, setApplyingProfile] = useState<string | null>(null)
  const [chatTextSize, setChatTextSize] = useState(() => localStorage.getItem('chat-text-size') || 'medium')
  const { theme, setTheme } = useTheme()

  const loadSettings = useCallback(() => {
    Promise.all([
      get<SettingsData>('/api/settings'),
      get<{ profiles: Profile[] }>('/api/profiles')
    ]).then(([s, p]) => {
      setSettings(s)
      setProfiles(p.profiles)
    }).catch(() => {})
  }, [])

  useEffect(() => { loadSettings() }, [loadSettings])

  useEffect(() => { if (active) loadSettings() }, [active, loadSettings])

  async function applyProfile(id: string) {
    setApplyingProfile(id)
    try {
      await post(`/api/profiles/${id}`)
      toast.success('Profile applied')
      loadSettings()
    } catch {
      toast.error('Failed to apply profile')
    } finally {
      setApplyingProfile(null)
    }
  }

  function update(section: string, field: string, value: string | number | boolean) {
    if (!settings) return
    setSettings({ ...settings, [section]: { ...(settings as any)[section], [field]: value } })
  }

  function updateProvider(name: string, patch: Partial<ProviderEntry>) {
    if (!settings) return
    const next = { ...settings.providers }
    next[name] = { ...(next[name] || { base_url: '', api_key: '' }), ...patch }
    setSettings({ ...settings, providers: next })
  }

  function addProvider() {
    if (!settings) return
    let name = 'new_provider'
    let i = 2
    while (settings.providers[name]) { name = `new_provider_${i++}` }
    setSettings({
      ...settings,
      providers: { ...settings.providers, [name]: { base_url: '', api_key: '' } },
    })
  }

  function deleteProvider(name: string) {
    if (!settings) return
    const { [name]: _, ...rest } = settings.providers
    setSettings({ ...settings, providers: rest })
  }

  function updateModel(alias: string, patch: Partial<ModelEntry>) {
    if (!settings) return
    const next = { ...settings.models }
    next[alias] = { ...(next[alias] || { provider: '', id: '', cost_in_per_mtok: 0, cost_out_per_mtok: 0, vision: false, context_window: 0 }), ...patch }
    setSettings({ ...settings, models: next })
  }

  function addModel() {
    if (!settings) return
    const providerNames = Object.keys(settings.providers)
    const defaultProvider = providerNames[0] || ''
    let alias = 'new_model'
    let i = 2
    while (settings.models[alias]) { alias = `new_model_${i++}` }
    setSettings({
      ...settings,
      models: {
        ...settings.models,
        [alias]: {
          provider: defaultProvider,
          id: '',
          cost_in_per_mtok: 0,
          cost_out_per_mtok: 0,
          vision: false,
          context_window: 0,
        },
      },
    })
  }

  function deleteModel(alias: string) {
    if (!settings) return
    const { [alias]: _, ...rest } = settings.models
    setSettings({ ...settings, models: rest })
  }

  async function save() {
    if (!settings) return
    setSaving(true)
    try {
      await post('/api/settings', settings)
      toast.success('Settings saved')
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
          {saving ? 'Saving...' : 'Save'}
        </Button>
      </div>

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

      {/* Text Size */}
      <SectionCard title="Chat Text Size">
        <div className="flex gap-2">
          {[
            { value: 'small', label: 'Small' },
            { value: 'medium', label: 'Medium' },
            { value: 'large', label: 'Large' },
          ].map(({ value, label }) => (
            <Button
              key={value}
              variant={chatTextSize === value ? 'default' : 'outline'}
              size="sm"
              onClick={() => {
                localStorage.setItem('chat-text-size', value)
                setChatTextSize(value)
                if (value === 'medium') {
                  document.body.removeAttribute('data-chat-size')
                } else {
                  document.body.setAttribute('data-chat-size', value)
                }
              }}
            >
              {label}
            </Button>
          ))}
        </div>
      </SectionCard>

      {/* Providers — BYOK: one entry per LLM endpoint */}
      <SectionCard title="LLM Providers">
        <p className="text-xs text-muted-foreground">
          Each provider is an OpenAI-compatible endpoint. The api_key lives here OR as
          <code className="mx-1 px-1 py-0.5 rounded bg-muted">${'{ENV_VAR}'}</code>
          referencing a secret from <code className="px-1 py-0.5 rounded bg-muted">.env</code>.
        </p>
        <div className="space-y-3">
          {Object.entries(settings.providers).map(([name, p]) => (
            <div key={name} className="rounded-md border border-border/40 bg-muted/20 p-3 space-y-2">
              <div className="flex items-center justify-between gap-2">
                <Input
                  value={name}
                  onChange={(e) => {
                    if (!settings) return
                    const newName = e.target.value
                    if (!newName || newName === name) return
                    const { [name]: val, ...rest } = settings.providers
                    setSettings({ ...settings, providers: { ...rest, [newName]: val } })
                  }}
                  className="w-40 font-mono text-xs bg-card border-border/40"
                />
                <Button variant="ghost" size="sm" onClick={() => deleteProvider(name)}>
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
              <Input
                placeholder="https://openrouter.ai/api/v1"
                value={p.base_url}
                onChange={(e) => updateProvider(name, { base_url: e.target.value })}
                className="bg-card border-border/40 text-xs font-mono"
              />
              <Input
                type="password"
                placeholder={p.api_key === '****' ? '**** (unchanged)' : 'sk-… or ${ENV_VAR}'}
                onChange={(e) => updateProvider(name, { api_key: e.target.value })}
                className="bg-card border-border/40 text-xs font-mono"
              />
            </div>
          ))}
          <Button variant="outline" size="sm" onClick={addProvider} className="gap-2">
            <Plus className="h-4 w-4" /> Add Provider
          </Button>
        </div>
      </SectionCard>

      {/* Models — reference a provider and declare id + cost + capabilities */}
      <SectionCard title="Models">
        <p className="text-xs text-muted-foreground">
          Each model has a nickname (alias), a provider, an id, and costs. Costs travel with
          the model so switching is one click.
        </p>
        <div className="space-y-3">
          {Object.entries(settings.models).map(([alias, m]) => (
            <div key={alias} className="rounded-md border border-border/40 bg-muted/20 p-3 space-y-2">
              <div className="flex items-center justify-between gap-2">
                <Input
                  value={alias}
                  onChange={(e) => {
                    if (!settings) return
                    const newAlias = e.target.value
                    if (!newAlias || newAlias === alias) return
                    const { [alias]: val, ...rest } = settings.models
                    setSettings({ ...settings, models: { ...rest, [newAlias]: val } })
                  }}
                  className="w-40 font-mono text-xs bg-card border-border/40"
                />
                <Button variant="ghost" size="sm" onClick={() => deleteModel(alias)}>
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <Label className="text-[10px] text-muted-foreground uppercase">Provider</Label>
                  <select
                    value={m.provider}
                    onChange={(e) => updateModel(alias, { provider: e.target.value })}
                    className="w-full bg-card border border-border/40 rounded-md px-2 py-1.5 text-xs"
                  >
                    {Object.keys(settings.providers).map((p) => (
                      <option key={p} value={p}>{p}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <Label className="text-[10px] text-muted-foreground uppercase">Model ID</Label>
                  <Input
                    value={m.id}
                    placeholder="meta-llama/llama-4-scout"
                    onChange={(e) => updateModel(alias, { id: e.target.value })}
                    className="bg-card border-border/40 text-xs font-mono"
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <Label className="text-[10px] text-muted-foreground uppercase">$/M input</Label>
                  <Input
                    type="number"
                    step="0.01"
                    value={m.cost_in_per_mtok}
                    onChange={(e) => updateModel(alias, { cost_in_per_mtok: parseFloat(e.target.value) || 0 })}
                    className="bg-card border-border/40 text-xs"
                  />
                </div>
                <div>
                  <Label className="text-[10px] text-muted-foreground uppercase">$/M output</Label>
                  <Input
                    type="number"
                    step="0.01"
                    value={m.cost_out_per_mtok}
                    onChange={(e) => updateModel(alias, { cost_out_per_mtok: parseFloat(e.target.value) || 0 })}
                    className="bg-card border-border/40 text-xs"
                  />
                </div>
              </div>
              <div className="flex items-center gap-4 pt-1">
                <label className="flex items-center gap-1.5 text-xs">
                  <input
                    type="checkbox"
                    checked={m.vision}
                    onChange={(e) => updateModel(alias, { vision: e.target.checked })}
                  />
                  Vision
                </label>
                <div className="flex items-center gap-1.5 text-xs">
                  <Label className="text-[10px] text-muted-foreground uppercase">Ctx</Label>
                  <Input
                    type="number"
                    value={m.context_window}
                    onChange={(e) => updateModel(alias, { context_window: parseInt(e.target.value) || 0 })}
                    className="w-24 bg-card border-border/40 text-xs"
                  />
                </div>
              </div>
            </div>
          ))}
          <Button variant="outline" size="sm" onClick={addModel} className="gap-2">
            <Plus className="h-4 w-4" /> Add Model
          </Button>
        </div>
      </SectionCard>

      {/* Routing — assign a model alias to each intelligence tier */}
      <SectionCard title="Intelligence Routing">
        <p className="text-xs text-muted-foreground">
          Assign a model alias to each tier. The classifier auto-routes between Fast and Smart
          based on query complexity when <b>auto-route</b> is enabled.
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {(['fast', 'smart', 'background', 'fallback'] as const).map((tier) => (
            <div key={tier} className="space-y-1.5">
              <Label className="text-xs text-muted-foreground uppercase">
                {tier === 'fast' && 'Fast (default)'}
                {tier === 'smart' && 'Smart (reasoning)'}
                {tier === 'background' && 'Background (cheap)'}
                {tier === 'fallback' && 'Fallback (safety net)'}
              </Label>
              <select
                value={settings.llm[tier] || ''}
                onChange={(e) => update('llm', tier, e.target.value)}
                className="w-full bg-muted/50 border border-border/40 rounded-md px-2 py-1.5 text-sm"
              >
                <option value="">(use fast)</option>
                {Object.keys(settings.models).map((alias) => (
                  <option key={alias} value={alias}>{alias}</option>
                ))}
              </select>
            </div>
          ))}
        </div>
        <div className="flex items-center justify-between pt-2">
          <div>
            <Label className="text-sm">Auto-route by classifier tier</Label>
            <p className="text-xs text-muted-foreground">
              When on, complex / planning queries automatically use Smart; simple queries use Fast.
            </p>
          </div>
          <Button
            variant={settings.llm.auto_route ? 'default' : 'outline'}
            size="sm"
            onClick={() => update('llm', 'auto_route', !settings.llm.auto_route)}
          >
            {settings.llm.auto_route ? 'On' : 'Off'}
          </Button>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-2">
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">Max Tokens</Label>
            <Input
              type="number"
              value={settings.llm.max_tokens}
              onChange={(e) => update('llm', 'max_tokens', parseInt(e.target.value))}
              className="bg-muted/50 border-border/40"
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">Temperature</Label>
            <Input
              type="number"
              step="0.1"
              value={settings.llm.temperature}
              onChange={(e) => update('llm', 'temperature', parseFloat(e.target.value))}
              className="bg-muted/50 border-border/40"
            />
          </div>
        </div>
      </SectionCard>

      {/* Agent */}
      <SectionCard title="Agent">
        <div className="space-y-1.5">
          <Label className="text-xs text-muted-foreground">Name</Label>
          <Input value={settings.agent.name} onChange={(e) => update('agent', 'name', e.target.value)} className="bg-muted/50 border-border/40" />
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
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

      {/* Profile Selector (G40) */}
      <SectionCard title="Agent Profile">
        <p className="text-sm text-muted-foreground mb-4">Select a specialized profile to adjust the agent's behavior and system prompt.</p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {profiles.map((p) => (
            <div 
              key={p.id} 
              className={`p-4 rounded-lg border transition-all ${
                settings.agent.profile === p.id 
                  ? 'border-primary bg-primary/5 ring-1 ring-primary' 
                  : 'border-border/40 bg-muted/20 hover:border-border'
              }`}
            >
              <div className="flex items-start justify-between gap-2 mb-2">
                <h3 className="font-semibold text-sm">{p.name}</h3>
                {settings.agent.profile === p.id && (
                  <span className="text-[10px] font-bold uppercase tracking-wider bg-primary text-primary-foreground px-1.5 py-0.5 rounded">Active</span>
                )}
              </div>
              <p className="text-xs text-muted-foreground mb-4 leading-relaxed line-clamp-2">{p.description}</p>
              <Button 
                variant={settings.agent.profile === p.id ? "secondary" : "outline"} 
                size="sm" 
                className="w-full h-8 text-xs"
                disabled={settings.agent.profile === p.id || applyingProfile !== null}
                onClick={() => applyProfile(p.id)}
              >
                {applyingProfile === p.id ? 'Applying...' : settings.agent.profile === p.id ? 'Active' : 'Apply Profile'}
              </Button>
            </div>
          ))}
        </div>
      </SectionCard>

      {/* Budget */}
      <SectionCard title="Budget">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
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
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
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
