import { useState, useEffect, useCallback } from 'react'
import { get, post } from '@/lib/api'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { 
  Sparkles, 
  Mic, 
  Search, 
  Globe, 
  Send, 
  BookOpen, 
  Server, 
  CheckCircle2, 
  Circle,
  Trash2
} from 'lucide-react'

const SERVICES = [
  {
    id: 'kie_ai',
    name: 'Kie.ai',
    description: 'Image generation (Z-Image) and music generation',
    placeholder: 'Paste Kie.ai API key',
    icon: Sparkles,
    color: 'text-violet-500',
  },
  {
    id: 'groq',
    name: 'Groq',
    description: 'Fast speech-to-text via Whisper',
    placeholder: 'Paste Groq API key',
    icon: Mic,
    color: 'text-orange-500',
  },
  {
    id: 'brave',
    name: 'Brave Search',
    description: 'Web search powered by Brave',
    placeholder: 'Paste Brave API key',
    icon: Search,
    color: 'text-orange-400',
  },
  {
    id: 'google',
    name: 'Google Search',
    description: 'Google Custom Search. Format: api_key:cx_id',
    placeholder: 'API_KEY:CX_ID',
    icon: Globe,
    color: 'text-blue-500',
  },
  {
    id: 'telegram',
    name: 'Telegram',
    description: 'Telegram bot channel for mobile chat',
    placeholder: 'Paste bot token from @BotFather',
    icon: Send,
    color: 'text-sky-500',
  },
  {
    id: 'notebooklm',
    name: 'NotebookLM',
    description: 'NotebookLM integration',
    placeholder: 'Paste NotebookLM cookie',
    icon: BookOpen,
    color: 'text-green-500',
  },
  {
    id: 'searxng',
    name: 'SearxNG',
    description: 'Self-hosted search. Value is the SearxNG base URL.',
    placeholder: 'https://searxng.example.com',
    icon: Server,
    color: 'text-teal-500',
  },
] as const

export default function ServicesTab({ active: isActive }: { active?: boolean }) {
  const [services, setServices] = useState<Record<string, string>>({})
  const [pendingValues, setPendingValues] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState<Record<string, boolean>>({})

  const load = useCallback(async () => {
    try {
      const data = await get<{ services: Record<string, string> }>('/api/settings')
      setServices(data.services || {})
      setLoading(false)
    } catch {
      toast.error('Failed to load services settings')
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => { if (isActive) load() }, [isActive, load])

  async function saveService(id: string, name: string) {
    const value = pendingValues[id]
    if (value === undefined) return

    setSaving(prev => ({ ...prev, [id]: true }))
    try {
      await post('/api/settings', { services: { [id]: value } })
      toast.success(`${name} saved`)
      setPendingValues(prev => {
        const next = { ...prev }
        delete next[id]
        return next
      })
      load() // reload to get masked value
    } catch {
      toast.error(`Failed to save ${name}`)
    } finally {
      setSaving(prev => ({ ...prev, [id]: false }))
    }
  }

  async function removeService(id: string, name: string) {
    setSaving(prev => ({ ...prev, [id]: true }))
    try {
      await post('/api/settings', { services: { [id]: '' } })
      toast.success(`${name} removed`)
      setPendingValues(prev => {
        const next = { ...prev }
        delete next[id]
        return next
      })
      load()
    } catch {
      toast.error(`Failed to remove ${name}`)
    } finally {
      setSaving(prev => ({ ...prev, [id]: false }))
    }
  }

  if (loading) return null

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 py-4 sm:py-6 space-y-8 pb-12">
      <header className="space-y-1">
        <h2 className="text-xl font-bold tracking-tight">Services</h2>
        <p className="text-sm text-muted-foreground">
          Configure API keys for external services. Adding a key automatically enables all features it powers.
        </p>
      </header>

      <div className="space-y-10">
        {SERVICES.map((service) => {
          const isConfigured = !!services[service.id]
          const isSaving = saving[service.id]
          const value = pendingValues[service.id] ?? ''

          return (
            <section key={service.id} className="space-y-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <service.icon className={`h-5 w-5 ${service.color}`} />
                  <h3 className="text-lg font-semibold">{service.name}</h3>
                </div>
                <div className="flex items-center gap-1.5">
                  {isConfigured ? (
                    <span className="flex items-center gap-1 text-xs font-medium text-green-500 bg-green-500/10 px-2 py-0.5 rounded-full border border-green-500/20">
                      <CheckCircle2 className="h-3 w-3" /> Connected
                    </span>
                  ) : (
                    <span className="flex items-center gap-1 text-xs font-medium text-muted-foreground bg-muted px-2 py-0.5 rounded-full border border-border">
                      <Circle className="h-3 w-3" /> Not configured
                    </span>
                  )}
                </div>
              </div>

              <div className="rounded-lg border border-border/40 bg-card p-4 space-y-4 shadow-sm">
                <p className="text-sm text-muted-foreground leading-relaxed">
                  {service.description}
                </p>

                <div className="space-y-2 pt-2">
                  <Label htmlFor={`service-${service.id}`}>API Key / Configuration</Label>
                  <div className="flex gap-2">
                    <Input
                      id={`service-${service.id}`}
                      type="password"
                      placeholder={isConfigured ? "••••••••••••••••" : service.placeholder}
                      value={value}
                      onChange={(e) => setPendingValues(prev => ({ ...prev, [service.id]: e.target.value }))}
                      className="font-mono"
                    />
                    <Button 
                      onClick={() => saveService(service.id, service.name)} 
                      disabled={isSaving || !value}
                      className="shrink-0"
                    >
                      {isSaving ? 'Saving...' : 'Save'}
                    </Button>
                    {isConfigured && (
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => removeService(service.id, service.name)}
                        disabled={isSaving}
                        className="text-destructive hover:text-destructive hover:bg-destructive/10 shrink-0"
                        title={`Remove ${service.name}`}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    )}
                  </div>
                </div>
              </div>
            </section>
          )
        })}
      </div>
    </div>
  )
}
