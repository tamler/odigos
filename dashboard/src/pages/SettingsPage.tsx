import { useEffect, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { get, post } from '@/lib/api'
import SetupModal from '@/components/SetupModal'

interface SettingsData {
  llm_api_key: string
  llm: { base_url: string; default_model: string; fallback_model: string; max_tokens: number; temperature: number }
  agent: { name: string; max_tool_turns: number; run_timeout_seconds: number }
  budget: { daily_limit_usd: number; monthly_limit_usd: number; warn_threshold: number }
  heartbeat: { interval_seconds: number; max_todos_per_tick: number; idle_think_interval: number }
  sandbox: { timeout_seconds: number; max_memory_mb: number; allow_network: boolean }
}

export default function SettingsPage() {
  const [settings, setSettings] = useState<SettingsData | null>(null)
  const [showSetup, setShowSetup] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    get<{ configured: boolean }>('/api/setup-status').then((data) => {
      if (!data.configured) setShowSetup(true)
    })
    get<SettingsData>('/api/settings')
      .then(setSettings)
      .catch(() => setShowSetup(true))
  }, [])

  function update(section: string, field: string, value: string | number | boolean) {
    if (!settings) return
    setSettings({ ...settings, [section]: { ...(settings as any)[section], [field]: value } })
    setSaved(false)
  }

  async function save() {
    if (!settings) return
    setSaving(true)
    try {
      await post('/api/settings', settings)
      setSaved(true)
    } finally {
      setSaving(false)
    }
  }

  if (!settings && !showSetup) {
    return <div className="flex-1 flex items-center justify-center text-muted-foreground">Loading...</div>
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <SetupModal open={showSetup} onComplete={() => { setShowSetup(false); window.location.reload() }} />
      <div className="max-w-2xl mx-auto p-6 space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">Settings</h1>
          <Button onClick={save} disabled={saving || saved}>
            {saved ? 'Saved' : saving ? 'Saving...' : 'Save Changes'}
          </Button>
        </div>
        <Tabs defaultValue="llm">
          <TabsList>
            <TabsTrigger value="llm">LLM</TabsTrigger>
            <TabsTrigger value="agent">Agent</TabsTrigger>
            <TabsTrigger value="budget">Budget</TabsTrigger>
            <TabsTrigger value="advanced">Advanced</TabsTrigger>
          </TabsList>

          <TabsContent value="llm" className="space-y-4 mt-4">
            <Card>
              <CardHeader><CardTitle>LLM Provider</CardTitle></CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label>Base URL</Label>
                  <Input value={settings?.llm.base_url || ''} onChange={(e) => update('llm', 'base_url', e.target.value)} />
                </div>
                <div className="space-y-2">
                  <Label>API Key</Label>
                  <Input type="password" placeholder="****" onChange={(e) => setSettings(s => s ? { ...s, llm_api_key: e.target.value } : s)} />
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label>Default Model</Label>
                    <Input value={settings?.llm.default_model || ''} onChange={(e) => update('llm', 'default_model', e.target.value)} />
                  </div>
                  <div className="space-y-2">
                    <Label>Fallback Model</Label>
                    <Input value={settings?.llm.fallback_model || ''} onChange={(e) => update('llm', 'fallback_model', e.target.value)} />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label>Max Tokens</Label>
                    <Input type="number" value={settings?.llm.max_tokens || 4096} onChange={(e) => update('llm', 'max_tokens', parseInt(e.target.value))} />
                  </div>
                  <div className="space-y-2">
                    <Label>Temperature</Label>
                    <Input type="number" step="0.1" value={settings?.llm.temperature || 0.7} onChange={(e) => update('llm', 'temperature', parseFloat(e.target.value))} />
                  </div>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="agent" className="space-y-4 mt-4">
            <Card>
              <CardHeader><CardTitle>Agent</CardTitle></CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label>Name</Label>
                  <Input value={settings?.agent.name || ''} onChange={(e) => update('agent', 'name', e.target.value)} />
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label>Max Tool Turns</Label>
                    <Input type="number" value={settings?.agent.max_tool_turns || 25} onChange={(e) => update('agent', 'max_tool_turns', parseInt(e.target.value))} />
                  </div>
                  <div className="space-y-2">
                    <Label>Run Timeout (seconds)</Label>
                    <Input type="number" value={settings?.agent.run_timeout_seconds || 300} onChange={(e) => update('agent', 'run_timeout_seconds', parseInt(e.target.value))} />
                  </div>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="budget" className="space-y-4 mt-4">
            <Card>
              <CardHeader><CardTitle>Budget Limits</CardTitle></CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label>Daily Limit (USD)</Label>
                    <Input type="number" step="0.5" value={settings?.budget.daily_limit_usd || 1} onChange={(e) => update('budget', 'daily_limit_usd', parseFloat(e.target.value))} />
                  </div>
                  <div className="space-y-2">
                    <Label>Monthly Limit (USD)</Label>
                    <Input type="number" step="1" value={settings?.budget.monthly_limit_usd || 20} onChange={(e) => update('budget', 'monthly_limit_usd', parseFloat(e.target.value))} />
                  </div>
                </div>
                <div className="space-y-2">
                  <Label>Warning Threshold (0-1)</Label>
                  <Input type="number" step="0.05" min="0" max="1" value={settings?.budget.warn_threshold || 0.8} onChange={(e) => update('budget', 'warn_threshold', parseFloat(e.target.value))} />
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="advanced" className="space-y-4 mt-4">
            <Card>
              <CardHeader><CardTitle>Heartbeat</CardTitle></CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-3 gap-4">
                  <div className="space-y-2">
                    <Label>Interval (s)</Label>
                    <Input type="number" value={settings?.heartbeat.interval_seconds || 30} onChange={(e) => update('heartbeat', 'interval_seconds', parseInt(e.target.value))} />
                  </div>
                  <div className="space-y-2">
                    <Label>Max Todos/Tick</Label>
                    <Input type="number" value={settings?.heartbeat.max_todos_per_tick || 3} onChange={(e) => update('heartbeat', 'max_todos_per_tick', parseInt(e.target.value))} />
                  </div>
                  <div className="space-y-2">
                    <Label>Idle Think (s)</Label>
                    <Input type="number" value={settings?.heartbeat.idle_think_interval || 900} onChange={(e) => update('heartbeat', 'idle_think_interval', parseInt(e.target.value))} />
                  </div>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>Sandbox</CardTitle></CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label>Timeout (s)</Label>
                    <Input type="number" value={settings?.sandbox.timeout_seconds || 5} onChange={(e) => update('sandbox', 'timeout_seconds', parseInt(e.target.value))} />
                  </div>
                  <div className="space-y-2">
                    <Label>Max Memory (MB)</Label>
                    <Input type="number" value={settings?.sandbox.max_memory_mb || 512} onChange={(e) => update('sandbox', 'max_memory_mb', parseInt(e.target.value))} />
                  </div>
                </div>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </div>
    </div>
  )
}
