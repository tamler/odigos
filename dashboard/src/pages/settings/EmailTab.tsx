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
import { Mail, Loader2 } from 'lucide-react'

interface EmailConfig {
  enabled: boolean
  address: string
  imap_host: string
  imap_port: number
  smtp_host: string
  smtp_port: number
  username: string
  password: string
  check_interval_ticks: number
}

const DEFAULT_CONFIG: EmailConfig = {
  enabled: false,
  address: '',
  imap_host: '',
  imap_port: 993,
  smtp_host: '',
  smtp_port: 587,
  username: '',
  password: '',
  check_interval_ticks: 10,
}

const PROVIDER_PRESETS: Record<string, { imap_host: string; imap_port: number; smtp_host: string; smtp_port: number; help: string }> = {
  gmail: {
    imap_host: 'imap.gmail.com', imap_port: 993,
    smtp_host: 'smtp.gmail.com', smtp_port: 587,
    help: 'Gmail requires an app-specific password. Go to Google Account > Security > 2-Step Verification > App passwords.',
  },
  outlook: {
    imap_host: 'outlook.office365.com', imap_port: 993,
    smtp_host: 'smtp.office365.com', smtp_port: 587,
    help: 'Use your regular Outlook/Microsoft 365 password, or an app password if 2FA is enabled.',
  },
  fastmail: {
    imap_host: 'mail.fastmail.com', imap_port: 993,
    smtp_host: 'mail.fastmail.com', smtp_port: 465,
    help: 'Generate an app-specific password at Fastmail > Settings > Privacy & Security > App Passwords.',
  },
  yahoo: {
    imap_host: 'imap.mail.yahoo.com', imap_port: 993,
    smtp_host: 'smtp.mail.yahoo.com', smtp_port: 465,
    help: 'Yahoo requires an app-specific password. Go to Account Security > Generate app password.',
  },
  protonmail: {
    imap_host: '127.0.0.1', imap_port: 1143,
    smtp_host: '127.0.0.1', smtp_port: 1025,
    help: 'ProtonMail requires the ProtonMail Bridge app running locally. Install and configure Bridge first.',
  },
  custom: {
    imap_host: '', imap_port: 993,
    smtp_host: '', smtp_port: 587,
    help: '',
  },
}

function detectProvider(config: EmailConfig): string {
  for (const [key, preset] of Object.entries(PROVIDER_PRESETS)) {
    if (key === 'custom') continue
    if (config.imap_host === preset.imap_host && config.smtp_host === preset.smtp_host) {
      return key
    }
  }
  return 'custom'
}

export default function EmailTab({ active: isActive }: { active?: boolean }) {
  const [config, setConfig] = useState<EmailConfig | null>(null)
  const [provider, setProvider] = useState('custom')
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ imap: string; smtp: string } | null>(null)
  const [passwordTouched, setPasswordTouched] = useState(false)

  const load = useCallback(async () => {
    try {
      const data = await get<any>('/api/settings')
      const email = data.email ? { ...DEFAULT_CONFIG, ...data.email } : { ...DEFAULT_CONFIG }
      setConfig(email)
      setProvider(detectProvider(email))
      setPasswordTouched(false)
      setTestResult(null)
    } catch {
      toast.error('Failed to load email settings')
    }
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => { if (isActive) load() }, [isActive, load])

  function updateConfig(updates: Partial<EmailConfig>) {
    if (!config) return
    setConfig({ ...config, ...updates })
  }

  function handleProviderChange(val: any) {
    if (!val) return
    setProvider(val)
    const preset = PROVIDER_PRESETS[val]
    if (preset) {
      updateConfig({
        imap_host: preset.imap_host,
        imap_port: preset.imap_port,
        smtp_host: preset.smtp_host,
        smtp_port: preset.smtp_port,
      })
    }
  }

  async function handleSave() {
    if (!config) return
    setSaving(true)
    try {
      const payload: Partial<EmailConfig> = { ...config }
      if (!passwordTouched || config.password === '****') {
        delete payload.password
      }
      await post('/api/settings', { email: payload })
      toast.success('Email settings saved')
      setPasswordTouched(false)
      load()
    } catch {
      toast.error('Failed to save email settings')
    } finally {
      setSaving(false)
    }
  }

  async function handleTest() {
    if (!config || testing) return
    setTesting(true)
    setTestResult(null)
    try {
      const payload: any = { ...config }
      if (!passwordTouched || config.password === '****') {
        delete payload.password
      }
      const result = await post<{ imap: string; smtp: string }>('/api/email/test', payload)
      setTestResult(result)
      if (result.imap === 'ok' && result.smtp === 'ok') {
        toast.success('Connection test passed')
      } else {
        toast.error('Connection test had errors')
      }
    } catch {
      toast.error('Connection test failed')
    } finally {
      setTesting(false)
    }
  }

  if (!config) return null

  const providerHelp = PROVIDER_PRESETS[provider]?.help || ''

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 py-4 sm:py-6 space-y-8">
      {/* Header */}
      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <Mail className="h-5 w-5 text-primary" />
          <h2 className="text-lg font-semibold">Email</h2>
        </div>
        <p className="text-sm text-muted-foreground leading-relaxed">
          Connect an email account to send and receive messages through the agent.
        </p>
      </div>

      {/* Enable toggle */}
      <div className="rounded-lg border border-border/40 bg-card p-4 space-y-6 shadow-sm">
        <div className="flex items-center justify-between">
          <div className="space-y-0.5">
            <Label className="text-base font-semibold">Enable Email</Label>
            <p className="text-xs text-muted-foreground">Allow the agent to check and send email.</p>
          </div>
          <Button
            variant="outline"
            size="sm"
            className={`h-8 ${config.enabled ? 'bg-primary/10 text-primary border-primary/20' : 'text-muted-foreground'}`}
            onClick={() => updateConfig({ enabled: !config.enabled })}
          >
            {config.enabled ? 'Enabled' : 'Disabled'}
          </Button>
        </div>

        {config.enabled && (
          <>
            {/* Provider preset */}
            <div className="pt-4 border-t border-border/20 space-y-4">
              <div className="space-y-2">
                <Label>Provider Preset</Label>
                <Select value={provider} onValueChange={handleProviderChange}>
                  <SelectTrigger className="w-full sm:w-[240px]">
                    <SelectValue placeholder="Select provider" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="gmail">Gmail</SelectItem>
                    <SelectItem value="outlook">Outlook / Microsoft 365</SelectItem>
                    <SelectItem value="fastmail">Fastmail</SelectItem>
                    <SelectItem value="yahoo">Yahoo Mail</SelectItem>
                    <SelectItem value="protonmail">ProtonMail (Bridge)</SelectItem>
                    <SelectItem value="custom">Custom</SelectItem>
                  </SelectContent>
                </Select>
                {providerHelp && (
                  <p className="text-xs text-muted-foreground">{providerHelp}</p>
                )}
              </div>
            </div>

            {/* Account section */}
            <div className="pt-4 border-t border-border/20 space-y-4">
              <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">Account</h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="email-address">Email Address</Label>
                  <Input
                    id="email-address"
                    type="email"
                    value={config.address}
                    onChange={(e) => updateConfig({ address: e.target.value })}
                    placeholder="you@example.com"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="email-username">Username</Label>
                  <Input
                    id="email-username"
                    value={config.username}
                    onChange={(e) => updateConfig({ username: e.target.value })}
                    placeholder="Usually your email address"
                  />
                </div>
                <div className="space-y-2 sm:col-span-2">
                  <Label htmlFor="email-password">Password</Label>
                  <Input
                    id="email-password"
                    type="password"
                    value={passwordTouched ? config.password : ''}
                    placeholder={config.password === '****' ? 'Password saved (enter new to change)' : 'App-specific password'}
                    onChange={(e) => {
                      setPasswordTouched(true)
                      updateConfig({ password: e.target.value })
                    }}
                  />
                </div>
              </div>
            </div>

            {/* IMAP section */}
            <div className="pt-4 border-t border-border/20 space-y-4">
              <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">IMAP (Incoming)</h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="imap-host">Host</Label>
                  <Input
                    id="imap-host"
                    value={config.imap_host}
                    onChange={(e) => updateConfig({ imap_host: e.target.value })}
                    placeholder="imap.example.com"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="imap-port">Port</Label>
                  <Input
                    id="imap-port"
                    type="number"
                    value={config.imap_port}
                    onChange={(e) => updateConfig({ imap_port: parseInt(e.target.value, 10) || 993 })}
                  />
                </div>
              </div>
            </div>

            {/* SMTP section */}
            <div className="pt-4 border-t border-border/20 space-y-4">
              <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">SMTP (Outgoing)</h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="smtp-host">Host</Label>
                  <Input
                    id="smtp-host"
                    value={config.smtp_host}
                    onChange={(e) => updateConfig({ smtp_host: e.target.value })}
                    placeholder="smtp.example.com"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="smtp-port">Port</Label>
                  <Input
                    id="smtp-port"
                    type="number"
                    value={config.smtp_port}
                    onChange={(e) => updateConfig({ smtp_port: parseInt(e.target.value, 10) || 587 })}
                  />
                </div>
              </div>
            </div>

            {/* Behavior section */}
            <div className="pt-4 border-t border-border/20 space-y-4">
              <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">Behavior</h3>
              <div className="space-y-2">
                <Label htmlFor="check-interval">Check Interval (heartbeat ticks)</Label>
                <div className="flex items-center gap-3">
                  <Input
                    id="check-interval"
                    type="number"
                    min={1}
                    max={100}
                    value={config.check_interval_ticks}
                    onChange={(e) => updateConfig({ check_interval_ticks: parseInt(e.target.value, 10) || 10 })}
                    className="w-24"
                  />
                  <span className="text-xs text-muted-foreground">
                    How many heartbeat cycles between email checks (lower = more frequent)
                  </span>
                </div>
              </div>
            </div>

            {/* Test result display */}
            {testResult && (
              <div className="pt-4 border-t border-border/20 space-y-2">
                <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">Test Results</h3>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-sm">
                  <div className={`p-2 rounded border ${testResult.imap === 'ok' ? 'border-green-500/30 bg-green-500/5 text-green-700 dark:text-green-400' : 'border-red-500/30 bg-red-500/5 text-red-700 dark:text-red-400'}`}>
                    <span className="font-medium">IMAP:</span> {testResult.imap}
                  </div>
                  <div className={`p-2 rounded border ${testResult.smtp === 'ok' ? 'border-green-500/30 bg-green-500/5 text-green-700 dark:text-green-400' : 'border-red-500/30 bg-red-500/5 text-red-700 dark:text-red-400'}`}>
                    <span className="font-medium">SMTP:</span> {testResult.smtp}
                  </div>
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {/* Actions */}
      {config.enabled && (
        <div className="flex flex-col sm:flex-row justify-end gap-3 pt-4 pb-12">
          <Button variant="outline" onClick={handleTest} disabled={testing} className="w-full sm:w-auto">
            {testing ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                Testing...
              </>
            ) : (
              'Test Connection'
            )}
          </Button>
          <Button onClick={handleSave} disabled={saving} className="w-full sm:w-auto">
            {saving ? 'Saving...' : 'Save Email Settings'}
          </Button>
        </div>
      )}
    </div>
  )
}
