import { useState, useEffect, useCallback } from 'react'
import { get, post } from '@/lib/api'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { CalendarDays, Loader2 } from 'lucide-react'

interface CalendarConfig {
  url: string
  username: string
  password: string
}

type Provider = 'google' | 'apple' | 'fastmail' | 'nextcloud' | 'radicale' | 'custom'

const PROVIDER_URLS: Record<Provider, string> = {
  google: 'https://caldav.google.com/',
  apple: 'https://caldav.icloud.com/',
  fastmail: 'https://caldav.fastmail.com/dav/calendars/user/{username}/',
  nextcloud: 'https://your-server.com/remote.php/dav/',
  radicale: 'http://localhost:5232/',
  custom: '',
}

const PROVIDER_HELP: Partial<Record<Provider, string>> = {
  google: 'Use an app-specific password. Enable CalDAV in Google Workspace settings.',
  apple: 'Use an app-specific password from appleid.apple.com',
  fastmail: 'Use your Fastmail app password. Replace {username} in the URL with your email.',
}

function detectProvider(url: string): Provider {
  if (url.includes('caldav.google.com')) return 'google'
  if (url.includes('caldav.icloud.com')) return 'apple'
  if (url.includes('caldav.fastmail.com')) return 'fastmail'
  if (url.includes('remote.php/dav')) return 'nextcloud'
  if (url.includes('localhost:5232')) return 'radicale'
  return 'custom'
}

export default function CalendarTab({ active: isActive }: { active?: boolean }) {
  const [config, setConfig] = useState<CalendarConfig | null>(null)
  const [provider, setProvider] = useState<Provider>('custom')
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ status: string; calendars?: string[]; detail?: string } | null>(null)

  const load = useCallback(async () => {
    try {
      const data = await get<any>('/api/settings')
      if (data.calendar) {
        setConfig(data.calendar)
        setProvider(detectProvider(data.calendar.url || ''))
      }
    } catch {
      toast.error('Failed to load calendar settings')
    }
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => { if (isActive) load() }, [isActive, load])

  function handleProviderChange(val: Provider) {
    if (!config) return
    setProvider(val)
    setTestResult(null)
    const url = PROVIDER_URLS[val]
    setConfig({ ...config, url })
  }

  function updateField(key: keyof CalendarConfig, value: string | boolean) {
    if (!config) return
    setConfig({ ...config, [key]: value })
    setTestResult(null)
  }

  async function handleSave() {
    if (!config) return
    setSaving(true)
    try {
      const payload: Record<string, any> = {
        url: config.url,
        username: config.username,
      }
      // Don't send masked password back
      if (config.password && config.password !== '****') {
        payload.password = config.password
      }
      await post('/api/settings', { calendar: payload })
      toast.success('Calendar settings saved')
      load()
    } catch {
      toast.error('Failed to save calendar settings')
    } finally {
      setSaving(false)
    }
  }

  async function handleTest() {
    if (!config || testing) return
    setTesting(true)
    setTestResult(null)
    try {
      const payload: Record<string, any> = {
        url: config.url,
        username: config.username,
      }
      if (config.password && config.password !== '****') {
        payload.password = config.password
      }
      const result = await post<{ status: string; calendars?: string[]; detail?: string }>('/api/calendar/test', payload)
      setTestResult(result)
      if (result.status === 'ok') {
        toast.success(`Connected -- found ${result.calendars?.length || 0} calendar(s)`)
      } else {
        toast.error(result.detail || 'Connection failed')
      }
    } catch {
      toast.error('Connection test failed')
      setTestResult({ status: 'error', detail: 'Request failed' })
    } finally {
      setTesting(false)
    }
  }

  if (!config) return null

  const helpText = PROVIDER_HELP[provider]

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 py-4 sm:py-6 space-y-8">
      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <CalendarDays className="h-5 w-5 text-primary" />
          <h2 className="text-lg font-semibold">Calendar</h2>
        </div>
        <p className="text-sm text-muted-foreground leading-relaxed">
          Connect a CalDAV calendar to let the agent read and manage your events.
        </p>
      </div>

      <div className="rounded-lg border border-border/40 bg-card p-4 space-y-6 shadow-sm">
          <div className="space-y-6">
            {/* Provider Preset */}
            <div className="space-y-2">
              <Label>Provider</Label>
              <Select value={provider} onValueChange={(val: any) => val && handleProviderChange(val as Provider)}>
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="Select a calendar provider" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="google">Google Calendar</SelectItem>
                  <SelectItem value="apple">Apple iCloud</SelectItem>
                  <SelectItem value="fastmail">Fastmail</SelectItem>
                  <SelectItem value="nextcloud">Nextcloud</SelectItem>
                  <SelectItem value="radicale">Radicale</SelectItem>
                  <SelectItem value="custom">Custom</SelectItem>
                </SelectContent>
              </Select>
              {helpText && (
                <p className="text-xs text-muted-foreground">{helpText}</p>
              )}
            </div>

            {/* CalDAV URL */}
            <div className="space-y-2">
              <Label htmlFor="caldav-url">CalDAV URL</Label>
              <Input
                id="caldav-url"
                value={config.url}
                onChange={(e) => updateField('url', e.target.value)}
                placeholder="https://caldav.example.com/"
              />
            </div>

            {/* Username */}
            <div className="space-y-2">
              <Label htmlFor="caldav-username">Username</Label>
              <Input
                id="caldav-username"
                value={config.username}
                onChange={(e) => updateField('username', e.target.value)}
                placeholder="user@example.com"
              />
            </div>

            {/* Password */}
            <div className="space-y-2">
              <Label htmlFor="caldav-password">Password</Label>
              <Input
                id="caldav-password"
                type="password"
                value={config.password}
                onChange={(e) => updateField('password', e.target.value)}
                placeholder="App-specific password"
              />
            </div>

            {/* Test Connection */}
            <div className="space-y-2">
              <Button
                variant="outline"
                onClick={handleTest}
                disabled={testing || !config.url || !config.username}
              >
                {testing ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    Testing...
                  </>
                ) : (
                  'Test Connection'
                )}
              </Button>
              {testResult && (
                <p className={`text-xs ${testResult.status === 'ok' ? 'text-green-600 dark:text-green-400' : 'text-destructive'}`}>
                  {testResult.status === 'ok'
                    ? `Connected. Calendars: ${testResult.calendars?.join(', ') || 'none found'}`
                    : testResult.detail || 'Connection failed'}
                </p>
              )}
            </div>
          </div>
      </div>

      <div className="flex justify-end pt-4 pb-12">
        <Button onClick={handleSave} disabled={saving} className="w-full sm:w-auto">
          {saving ? 'Saving...' : 'Save Calendar Settings'}
        </Button>
      </div>
    </div>
  )
}
