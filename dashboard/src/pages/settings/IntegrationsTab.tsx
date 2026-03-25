import { useState, useEffect, useCallback } from 'react'
import { get, post } from '@/lib/api'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Send, Mail, CheckCircle2, Circle } from 'lucide-react'

interface IntegrationSettings {
  telegram_bot_token?: string
  telegram_configured: boolean
  telegram: {
    enabled: boolean
  }
  email: {
    enabled: boolean
    address: string
    imap_host: string
    imap_port: number
    smtp_host: string
    smtp_port: number
    username: string
    password?: string
  }
}

export default function IntegrationsTab({ active: isActive }: { active?: boolean }) {
  const [settings, setSettings] = useState<IntegrationSettings | null>(null)
  const [telegramToken, setTelegramToken] = useState('')
  const [emailValues, setEmailValues] = useState<IntegrationSettings['email'] | null>(null)
  const [savingTelegram, setSavingTelegram] = useState(false)
  const [savingEmail, setSavingEmail] = useState(false)

  const load = useCallback(async () => {
    try {
      const data = await get<IntegrationSettings>('/api/settings')
      setSettings(data)
      setEmailValues(data.email)
    } catch {
      toast.error('Failed to load integration settings')
    }
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => { if (isActive) load() }, [isActive, load])

  async function saveTelegram() {
    setSavingTelegram(true)
    try {
      await post('/api/settings', { telegram_bot_token: telegramToken })
      toast.success('Telegram configuration saved. Restart required.')
      setTelegramToken('')
      load()
    } catch {
      toast.error('Failed to save Telegram settings')
    } finally {
      setSavingTelegram(false)
    }
  }

  async function saveEmail() {
    if (!emailValues) return
    setSavingEmail(true)
    try {
      await post('/api/settings', { email: emailValues })
      toast.success('Email configuration saved.')
      load()
    } catch {
      toast.error('Failed to save email settings')
    } finally {
      setSavingEmail(false)
    }
  }

  if (!settings || !emailValues) return null

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 py-4 sm:py-6 space-y-8">
      {/* Telegram Integration */}
      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Send className="h-5 w-5 text-sky-500" />
            <h2 className="text-lg font-semibold">Telegram</h2>
          </div>
          <div className="flex items-center gap-1.5">
            {settings.telegram_configured ? (
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
          <div className="space-y-2 text-sm text-muted-foreground leading-relaxed">
            <p>Connect your agent to Telegram to chat on the go.</p>
            <ol className="list-decimal list-inside space-y-1 ml-1">
              <li>Open Telegram and message <a href="https://t.me/BotFather" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline font-medium">@BotFather</a></li>
              <li>Send <code className="bg-muted px-1 rounded text-foreground font-mono">/newbot</code> and follow instructions</li>
              <li>Copy the API Token provided and paste it below</li>
            </ol>
          </div>

          <div className="space-y-2 pt-2">
            <Label htmlFor="telegram-token">Bot Token</Label>
            <div className="flex gap-2">
              <Input
                id="telegram-token"
                type="password"
                placeholder={settings.telegram_configured ? "••••••••••••••••" : "Paste token here"}
                value={telegramToken}
                onChange={(e) => setTelegramToken(e.target.value)}
                className="font-mono"
              />
              <Button onClick={saveTelegram} disabled={savingTelegram || !telegramToken}>
                {savingTelegram ? 'Saving...' : 'Save'}
              </Button>
            </div>
            {settings.telegram_configured && (
              <p className="text-[11px] text-muted-foreground italic">Note: Changing the token requires a server restart.</p>
            )}
          </div>
        </div>
      </section>

      {/* Email Integration */}
      <section className="space-y-4 pb-8">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Mail className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold">Email</h2>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              className={`h-8 ${emailValues.enabled ? 'bg-primary/10 text-primary border-primary/20' : 'text-muted-foreground'}`}
              onClick={() => setEmailValues({ ...emailValues, enabled: !emailValues.enabled })}
            >
              {emailValues.enabled ? 'Enabled' : 'Disabled'}
            </Button>
          </div>
        </div>

        <div className="rounded-lg border border-border/40 bg-card p-4 space-y-4 shadow-sm">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="email-address">Email Address</Label>
              <Input
                id="email-address"
                placeholder="agent@example.com"
                value={emailValues.address}
                onChange={(e) => setEmailValues({ ...emailValues, address: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="email-username">Username</Label>
              <Input
                id="email-username"
                placeholder="IMAP/SMTP Username"
                value={emailValues.username}
                onChange={(e) => setEmailValues({ ...emailValues, username: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="email-password">Password</Label>
              <Input
                id="email-password"
                type="password"
                placeholder="Leave empty to keep current"
                value={emailValues.password || ''}
                onChange={(e) => setEmailValues({ ...emailValues, password: e.target.value })}
              />
            </div>
          </div>

          <div className="border-t border-border/40 pt-4 grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="space-y-2">
              <Label htmlFor="imap-host">IMAP Host</Label>
              <Input
                id="imap-host"
                placeholder="imap.example.com"
                value={emailValues.imap_host}
                onChange={(e) => setEmailValues({ ...emailValues, imap_host: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="imap-port">IMAP Port</Label>
              <Input
                id="imap-port"
                type="number"
                value={emailValues.imap_port}
                onChange={(e) => setEmailValues({ ...emailValues, imap_port: parseInt(e.target.value) || 993 })}
              />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="space-y-2">
              <Label htmlFor="smtp-host">SMTP Host</Label>
              <Input
                id="smtp-host"
                placeholder="smtp.example.com"
                value={emailValues.smtp_host}
                onChange={(e) => setEmailValues({ ...emailValues, smtp_host: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="smtp-port">SMTP Port</Label>
              <Input
                id="smtp-port"
                type="number"
                value={emailValues.smtp_port}
                onChange={(e) => setEmailValues({ ...emailValues, smtp_port: parseInt(e.target.value) || 587 })}
              />
            </div>
          </div>

          <div className="flex justify-end pt-2">
            <Button onClick={saveEmail} disabled={savingEmail}>
              {savingEmail ? 'Saving...' : 'Save Email Configuration'}
            </Button>
          </div>
        </div>
      </section>
    </div>
  )
}
