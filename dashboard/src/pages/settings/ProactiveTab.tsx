import { useEffect, useState } from 'react'
import { get, patch } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { toast } from 'sonner'

export default function ProactiveTab() {
  const [enabled, setEnabled] = useState(true)
  const [frequency, setFrequency] = useState(4)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    get<{ enabled: boolean; max_cycles_per_hour: number }>('/api/settings/proactive')
      .then((data) => {
        setEnabled(data.enabled)
        setFrequency(data.max_cycles_per_hour)
      })
      .catch(() => {})
  }, [])

  const save = async () => {
    setSaving(true)
    try {
      await patch('/api/settings/proactive', { enabled, max_cycles_per_hour: frequency })
      toast.success('Proactive settings updated')
    } catch {
      toast.error('Failed to save')
    }
    setSaving(false)
  }

  const freqLabel = frequency <= 1 ? 'Low' : frequency <= 4 ? 'Medium' : 'High'

  return (
    <div className="space-y-6 max-w-md">
      <div>
        <h3 className="text-sm font-medium mb-1">Proactive Mode</h3>
        <p className="text-xs text-muted-foreground mb-3">
          When enabled, your agent proactively researches topics, surfaces insights, and delivers findings to the Activity page.
        </p>
        <label className="flex items-center gap-3 cursor-pointer">
          <div
            className={`w-10 h-6 rounded-full transition-colors relative ${enabled ? 'bg-primary' : 'bg-muted'}`}
            onClick={() => setEnabled(!enabled)}
          >
            <div className={`w-4 h-4 bg-white rounded-full absolute top-1 transition-transform ${enabled ? 'translate-x-5' : 'translate-x-1'}`} />
          </div>
          <span className="text-sm">{enabled ? 'Enabled' : 'Disabled'}</span>
        </label>
      </div>

      {enabled && (
        <div>
          <h3 className="text-sm font-medium mb-1">Frequency</h3>
          <p className="text-xs text-muted-foreground mb-3">
            How often the agent looks for proactive opportunities. Higher means more findings but more token usage.
          </p>
          <div className="flex items-center gap-4">
            <input
              type="range"
              min={1}
              max={8}
              value={frequency}
              onChange={(e) => setFrequency(Number(e.target.value))}
              className="flex-1 accent-primary"
            />
            <span className="text-sm font-medium w-16">{freqLabel} ({frequency}/hr)</span>
          </div>
        </div>
      )}

      <Button onClick={save} disabled={saving} size="sm">
        {saving ? 'Saving...' : 'Save'}
      </Button>
    </div>
  )
}
