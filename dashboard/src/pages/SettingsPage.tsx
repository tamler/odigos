import { useEffect, useState } from 'react'
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
  llm: { base_url: string; default_model: string; fallback_model: string; max_tokens: number; temperature: number }
  agent: { name: string; max_tool_turns: number; run_timeout_seconds: number }
  budget: { daily_limit_usd: number; monthly_limit_usd: number; warn_threshold: number }
  heartbeat: { interval_seconds: number; max_todos_per_tick: number; idle_think_interval: number }
  sandbox: { timeout_seconds: number; max_memory_mb: number; allow_network: boolean }
}

interface Props {
  needsSetup?: boolean
}

export default function SettingsPage({ needsSetup }: Props) {
  const [settings, setSettings] = useState<SettingsData | null>(null)
  const [saving, setSaving] = useState(false)
  const [selectedProvider, setSelectedProvider] = useState<string | null>(null)
  const { theme, setTheme } = useTheme()

  useEffect(() => {
    get<SettingsData>('/api/settings')
      .then(setSettings)
      .catch(() => {})
  }, [])

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
    } catch (e) {
      toast.error('Failed to save settings')
    } finally {
      setSaving(false)
    }
  }

  if (!settings) {
    return <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">Loading...</div>
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-2xl mx-auto px-6 py-8 space-y-8">
        {/* Header */}
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold">Settings</h1>
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
        <section className="space-y-4">
          <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">Appearance</h2>
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
        </section>

        {/* LLM Provider */}
        <section className="space-y-4">
          <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">LLM Provider</h2>
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
            <div className="space-y-2">
              <Label className="text-xs text-muted-foreground">Base URL</Label>
              <Input value={settings.llm.base_url} onChange={(e) => update('llm', 'base_url', e.target.value)} className="bg-muted/50 border-border/40" />
            </div>
            <div className="space-y-2">
              <Label className="text-xs text-muted-foreground">API Key</Label>
              <Input type="password" placeholder="****" onChange={(e) => setSettings(s => s ? { ...s, llm_api_key: e.target.value } : s)} className="bg-muted/50 border-border/40" />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label className="text-xs text-muted-foreground">Default Model</Label>
                <Input value={settings.llm.default_model} onChange={(e) => update('llm', 'default_model', e.target.value)} className="bg-muted/50 border-border/40" />
              </div>
              <div className="space-y-2">
                <Label className="text-xs text-muted-foreground">Fallback Model</Label>
                <Input value={settings.llm.fallback_model} onChange={(e) => update('llm', 'fallback_model', e.target.value)} className="bg-muted/50 border-border/40" />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label className="text-xs text-muted-foreground">Max Tokens</Label>
                <Input type="number" value={settings.llm.max_tokens} onChange={(e) => update('llm', 'max_tokens', parseInt(e.target.value))} className="bg-muted/50 border-border/40" />
              </div>
              <div className="space-y-2">
                <Label className="text-xs text-muted-foreground">Temperature</Label>
                <Input type="number" step="0.1" value={settings.llm.temperature} onChange={(e) => update('llm', 'temperature', parseFloat(e.target.value))} className="bg-muted/50 border-border/40" />
              </div>
            </div>
          </div>
        </section>

        {/* Agent */}
        <section className="space-y-4">
          <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">Agent</h2>
          <div className="grid gap-4">
            <div className="space-y-2">
              <Label className="text-xs text-muted-foreground">Name</Label>
              <Input value={settings.agent.name} onChange={(e) => update('agent', 'name', e.target.value)} className="bg-muted/50 border-border/40" />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label className="text-xs text-muted-foreground">Max Tool Turns</Label>
                <Input type="number" value={settings.agent.max_tool_turns} onChange={(e) => update('agent', 'max_tool_turns', parseInt(e.target.value))} className="bg-muted/50 border-border/40" />
              </div>
              <div className="space-y-2">
                <Label className="text-xs text-muted-foreground">Run Timeout (s)</Label>
                <Input type="number" value={settings.agent.run_timeout_seconds} onChange={(e) => update('agent', 'run_timeout_seconds', parseInt(e.target.value))} className="bg-muted/50 border-border/40" />
              </div>
            </div>
          </div>
        </section>

        {/* Budget */}
        <section className="space-y-4">
          <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">Budget</h2>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label className="text-xs text-muted-foreground">Daily Limit (USD)</Label>
              <Input type="number" step="0.5" value={settings.budget.daily_limit_usd} onChange={(e) => update('budget', 'daily_limit_usd', parseFloat(e.target.value))} className="bg-muted/50 border-border/40" />
            </div>
            <div className="space-y-2">
              <Label className="text-xs text-muted-foreground">Monthly Limit (USD)</Label>
              <Input type="number" step="1" value={settings.budget.monthly_limit_usd} onChange={(e) => update('budget', 'monthly_limit_usd', parseFloat(e.target.value))} className="bg-muted/50 border-border/40" />
            </div>
          </div>
        </section>

        {/* Advanced */}
        <section className="space-y-4">
          <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">Advanced</h2>
          <div className="grid grid-cols-3 gap-4">
            <div className="space-y-2">
              <Label className="text-xs text-muted-foreground">Heartbeat (s)</Label>
              <Input type="number" value={settings.heartbeat.interval_seconds} onChange={(e) => update('heartbeat', 'interval_seconds', parseInt(e.target.value))} className="bg-muted/50 border-border/40" />
            </div>
            <div className="space-y-2">
              <Label className="text-xs text-muted-foreground">Sandbox Timeout (s)</Label>
              <Input type="number" value={settings.sandbox.timeout_seconds} onChange={(e) => update('sandbox', 'timeout_seconds', parseInt(e.target.value))} className="bg-muted/50 border-border/40" />
            </div>
            <div className="space-y-2">
              <Label className="text-xs text-muted-foreground">Sandbox Memory (MB)</Label>
              <Input type="number" value={settings.sandbox.max_memory_mb} onChange={(e) => update('sandbox', 'max_memory_mb', parseInt(e.target.value))} className="bg-muted/50 border-border/40" />
            </div>
          </div>
        </section>

        {/* Bottom spacing */}
        <div className="h-8" />
      </div>
    </div>
  )
}
