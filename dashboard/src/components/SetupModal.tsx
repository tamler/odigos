import { useState } from 'react'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { post } from '@/lib/api'

const PROVIDERS = [
  { id: 'openrouter', name: 'OpenRouter', url: 'https://openrouter.ai/api/v1', model: 'anthropic/claude-sonnet-4', fallback: 'google/gemini-2.0-flash-001' },
  { id: 'openai', name: 'OpenAI', url: 'https://api.openai.com/v1', model: 'gpt-4o', fallback: 'gpt-4o-mini' },
  { id: 'ollama', name: 'Ollama (local)', url: 'http://host.docker.internal:11434/v1', model: 'llama3.2', fallback: 'llama3.2' },
  { id: 'lmstudio', name: 'LM Studio (local)', url: 'http://host.docker.internal:1234/v1', model: 'default', fallback: 'default' },
  { id: 'custom', name: 'Custom', url: '', model: '', fallback: '' },
]

interface Props {
  open: boolean
  onComplete: () => void
}

export default function SetupModal({ open, onComplete }: Props) {
  const [provider, setProvider] = useState('openrouter')
  const [baseUrl, setBaseUrl] = useState(PROVIDERS[0].url)
  const [apiKey, setLlmApiKey] = useState('')
  const [model, setModel] = useState(PROVIDERS[0].model)
  const [fallback, setFallback] = useState(PROVIDERS[0].fallback)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  function onProviderChange(id: string | null) {
    if (!id) return
    setProvider(id)
    const p = PROVIDERS.find((p) => p.id === id)
    if (p) {
      setBaseUrl(p.url)
      setModel(p.model)
      setFallback(p.fallback)
    }
  }

  async function handleSave() {
    setSaving(true)
    setError('')
    try {
      await post('/api/settings', {
        llm_api_key: apiKey || 'no-key-needed',
        llm: {
          base_url: baseUrl,
          default_model: model,
          fallback_model: fallback,
        },
      })
      onComplete()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  const isLocal = baseUrl.includes('localhost') || baseUrl.includes('host.docker.internal')

  return (
    <Dialog open={open} onOpenChange={() => {}} disablePointerDismissal>
      <DialogContent className="sm:max-w-md" showCloseButton={false}>
        <DialogHeader>
          <DialogTitle>Welcome to Odigos</DialogTitle>
          <DialogDescription>Configure your LLM provider to get started.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="space-y-2">
            <Label>Provider</Label>
            <Select value={provider} onValueChange={onProviderChange}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {PROVIDERS.map((p) => (
                  <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label>Base URL</Label>
            <Input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://..." />
          </div>
          <div className="space-y-2">
            <Label>API Key {isLocal && '(optional for local models)'}</Label>
            <Input type="password" value={apiKey} onChange={(e) => setLlmApiKey(e.target.value)} placeholder={isLocal ? 'Press Enter to skip' : 'sk-...'} />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-2">
              <Label>Model</Label>
              <Input value={model} onChange={(e) => setModel(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label>Fallback Model</Label>
              <Input value={fallback} onChange={(e) => setFallback(e.target.value)} />
            </div>
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <Button className="w-full" onClick={handleSave} disabled={saving || (!baseUrl || !model)}>
            {saving ? 'Saving...' : 'Save & Start'}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
