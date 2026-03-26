import { useState, useEffect, useCallback } from 'react'
import { get, post } from '@/lib/api'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { 
  Select, 
  SelectContent, 
  SelectItem, 
  SelectTrigger, 
  SelectValue 
} from '@/components/ui/select'
import { MessageCircle } from 'lucide-react'
import { AssistantConfig } from '@/layouts/AppLayout'

export default function AssistantTab({ active: isActive }: { active?: boolean }) {
  const [config, setConfig] = useState<AssistantConfig | null>(null)

  const load = useCallback(async () => {
    try {
      const data = await get<any>('/api/settings')
      if (data.assistant) setConfig(data.assistant)
    } catch {
      toast.error('Failed to load assistant settings')
    }
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => { if (isActive) load() }, [isActive, load])

  async function updateField(key: keyof AssistantConfig, value: any) {
    if (!config) return
    const next = { ...config, [key]: value }
    setConfig(next)
    try {
      await post('/api/settings', { assistant: { [key]: value } })
      toast.success('Assistant setting updated')
    } catch {
      toast.error('Failed to update assistant setting')
      load() // revert
    }
  }

  if (!config) return null

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 py-4 sm:py-6 space-y-8">
      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <MessageCircle className="h-5 w-5 text-primary" />
          <h2 className="text-lg font-semibold">Assistant Bubble</h2>
        </div>
        <p className="text-sm text-muted-foreground leading-relaxed">
          Configure the floating assistant bubble that follows you across the platform.
        </p>
      </div>

      <div className="rounded-lg border border-border/40 bg-card p-4 space-y-6 shadow-sm">
        <div className="flex items-center justify-between">
          <div className="space-y-0.5">
            <Label className="text-base font-semibold">Enable Bubble</Label>
            <p className="text-xs text-muted-foreground">Show the floating chat button on non-chat pages.</p>
          </div>
          <Button
            variant="outline"
            size="sm"
            className={`h-8 ${config.enabled ? 'bg-primary/10 text-primary border-primary/20' : 'text-muted-foreground'}`}
            onClick={() => updateField('enabled', !config.enabled)}
          >
            {config.enabled ? 'Enabled' : 'Disabled'}
          </Button>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-12 gap-y-6 pt-4 border-t border-border/20">
          <div className="flex items-center justify-between">
            <Label className="text-sm font-medium">Show Transcript</Label>
            <Button
              variant="ghost"
              size="sm"
              className={`h-8 ${config.show_transcript ? 'text-primary' : 'text-muted-foreground'}`}
              onClick={() => updateField('show_transcript', !config.show_transcript)}
            >
              {config.show_transcript ? 'On' : 'Off'}
            </Button>
          </div>

          <div className="flex items-center justify-between">
            <Label className="text-sm font-medium">Text Input</Label>
            <Button
              variant="ghost"
              size="sm"
              className={`h-8 ${config.text_input ? 'text-primary' : 'text-muted-foreground'}`}
              onClick={() => updateField('text_input', !config.text_input)}
            >
              {config.text_input ? 'On' : 'Off'}
            </Button>
          </div>

          <div className="flex items-center justify-between">
            <Label className="text-sm font-medium">Voice Input</Label>
            <Button
              variant="ghost"
              size="sm"
              className={`h-8 ${config.voice_input ? 'text-primary' : 'text-muted-foreground'}`}
              onClick={() => updateField('voice_input', !config.voice_input)}
            >
              {config.voice_input ? 'On' : 'Off'}
            </Button>
          </div>

          <div className="flex items-center justify-between">
            <Label className="text-sm font-medium">Auto-read Responses</Label>
            <Button
              variant="ghost"
              size="sm"
              className={`h-8 ${config.auto_read ? 'text-primary' : 'text-muted-foreground'}`}
              onClick={() => updateField('auto_read', !config.auto_read)}
            >
              {config.auto_read ? 'On' : 'Off'}
            </Button>
          </div>
        </div>

        <div className="pt-4 border-t border-border/20 space-y-2">
          <Label className="text-sm font-medium">Position</Label>
          <Select 
            value={config.position} 
            onValueChange={(val: any) => updateField('position', val)}
          >
            <SelectTrigger className="w-[200px]">
              <SelectValue placeholder="Select position" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="bottom-right">Bottom Right</SelectItem>
              <SelectItem value="bottom-left">Bottom Left</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>
    </div>
  )
}
