import { useState, useEffect, useCallback } from 'react'
import { get, post } from '@/lib/api'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Puzzle, ExternalLink, Check, X, AlertCircle } from 'lucide-react'

interface ConfigKey {
  key: string
  required: boolean
  description: string
  type: string
  configured: boolean
}

interface Requirement {
  label: string
  url: string
}

interface Plugin {
  id: string
  name: string
  description: string
  category: string
  status: string
  error_message?: string
  requires: Requirement[]
  config_keys: ConfigKey[]
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    active: 'bg-green-500/10 text-green-500 border-green-500/20',
    available: 'bg-muted text-muted-foreground border-border',
    skipped: 'bg-muted text-muted-foreground border-border',
    error: 'bg-red-500/10 text-red-500 border-red-500/20',
  }
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full border ${styles[status] || styles.available}`}>
      {status}
    </span>
  )
}

function CategoryBadge({ category }: { category: string }) {
  return (
    <span className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary border border-primary/20">
      {category}
    </span>
  )
}

function PluginCard({ plugin, onSaved }: { plugin: Plugin; onSaved: () => void }) {
  const [expanded, setExpanded] = useState(false)
  const [values, setValues] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)

  const hasConfigKeys = plugin.config_keys.length > 0

  async function handleSave() {
    setSaving(true)
    try {
      const typed: Record<string, string | boolean | number> = {}
      for (const ck of plugin.config_keys) {
        const v = values[ck.key]
        if (v === undefined || v === '') continue
        if (ck.type === 'boolean') typed[ck.key] = v === 'true'
        else if (ck.type === 'number') typed[ck.key] = Number(v)
        else typed[ck.key] = v
      }
      await post(`/api/plugins/${plugin.id}/configure`, { values: typed })
      toast.success('Configuration saved. Restart to apply.')
      onSaved()
    } catch {
      toast.error('Failed to save configuration')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="border rounded-lg p-4 space-y-3">
      <div className="flex items-start justify-between">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <h3 className="font-medium text-sm">{plugin.name}</h3>
            <CategoryBadge category={plugin.category} />
            <StatusBadge status={plugin.status} />
          </div>
          <p className="text-sm text-muted-foreground">{plugin.description}</p>
        </div>
        {hasConfigKeys && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? 'Close' : 'Configure'}
          </Button>
        )}
      </div>

      {plugin.error_message && (
        <div className="flex items-center gap-2 text-sm text-red-500">
          <AlertCircle className="h-4 w-4" />
          {plugin.error_message}
        </div>
      )}

      {plugin.requires.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {plugin.requires.map((r, i) => (
            <a
              key={i}
              href={r.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
            >
              <ExternalLink className="h-3 w-3" />
              {r.label}
            </a>
          ))}
        </div>
      )}

      {expanded && hasConfigKeys && (
        <div className="space-y-3 pt-2 border-t">
          {plugin.config_keys.map((ck) => (
            <div key={ck.key} className="space-y-1">
              <div className="flex items-center gap-2">
                <label className="text-sm font-medium">{ck.key}</label>
                {ck.required && <span className="text-xs text-red-500">required</span>}
                {ck.configured ? (
                  <Check className="h-3 w-3 text-green-500" />
                ) : (
                  <X className="h-3 w-3 text-muted-foreground" />
                )}
              </div>
              <p className="text-xs text-muted-foreground">{ck.description}</p>
              {ck.type === 'boolean' ? (
                <select
                  className="w-full px-3 py-1.5 rounded-md border bg-background text-sm"
                  value={values[ck.key] || ''}
                  onChange={(e) => setValues({ ...values, [ck.key]: e.target.value })}
                >
                  <option value="">-- select --</option>
                  <option value="true">Enabled</option>
                  <option value="false">Disabled</option>
                </select>
              ) : (
                <input
                  type={ck.type === 'secret' ? 'password' : 'text'}
                  placeholder={ck.type === 'secret' ? '********' : `Enter ${ck.key}`}
                  className="w-full px-3 py-1.5 rounded-md border bg-background text-sm"
                  value={values[ck.key] || ''}
                  onChange={(e) => setValues({ ...values, [ck.key]: e.target.value })}
                />
              )}
            </div>
          ))}
          <Button size="sm" onClick={handleSave} disabled={saving}>
            {saving ? 'Saving...' : 'Save Configuration'}
          </Button>
        </div>
      )}
    </div>
  )
}

export default function PluginsPage() {
  const [plugins, setPlugins] = useState<Plugin[]>([])

  const load = useCallback(async () => {
    try {
      const data = await get<{ plugins: Plugin[] }>('/api/plugins')
      setPlugins(data.plugins)
    } catch {
      toast.error('Failed to load plugins')
    }
  }, [])

  useEffect(() => { load() }, [load])

  const active = plugins.filter((p) => p.status === 'active')
  const available = plugins.filter((p) => p.status !== 'active')

  return (
    <div className="flex-1 overflow-auto">
      <div className="max-w-4xl mx-auto px-6 py-8 space-y-8">
        <div className="flex items-center gap-3">
          <Puzzle className="h-5 w-5 text-muted-foreground" />
          <h1 className="text-lg font-semibold">Plugins</h1>
        </div>

        {active.length > 0 && (
          <div className="space-y-3">
            <h2 className="text-sm font-medium text-muted-foreground">Active</h2>
            <div className="space-y-3">
              {active.map((p) => (
                <PluginCard key={p.id} plugin={p} onSaved={load} />
              ))}
            </div>
          </div>
        )}

        {available.length > 0 && (
          <div className="space-y-3">
            <h2 className="text-sm font-medium text-muted-foreground">Available</h2>
            <div className="space-y-3">
              {available.map((p) => (
                <PluginCard key={p.id} plugin={p} onSaved={load} />
              ))}
            </div>
          </div>
        )}

        {plugins.length === 0 && (
          <p className="text-sm text-muted-foreground">No plugins found.</p>
        )}
      </div>
    </div>
  )
}
