import { useEffect, useState, useCallback } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { get } from '@/lib/api'
import { changePassword, logout } from '@/lib/auth'
import { toast } from 'sonner'
import { Copy, LogOut } from 'lucide-react'

interface AuthMe {
  username: string
  display_name: string
}

interface SettingsData {
  api_key: string
}

interface Props {
  active?: boolean
}

function SectionCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border/40 bg-card">
      <div className="px-5 py-3 border-b border-border/40">
        <h2 className="text-sm font-medium">{title}</h2>
      </div>
      <div className="px-5 py-4 space-y-4">
        {children}
      </div>
    </div>
  )
}

export default function AccountTab({ active }: Props) {
  const [me, setMe] = useState<AuthMe | null>(null)
  const [apiKey, setApiKey] = useState<string>('')
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [changingPassword, setChangingPassword] = useState(false)

  const loadData = useCallback(() => {
    get<AuthMe>('/api/auth/me')
      .then(setMe)
      .catch(() => {})
    get<SettingsData>('/api/settings')
      .then((s) => setApiKey(s.api_key || ''))
      .catch(() => {})
  }, [])

  useEffect(() => { loadData() }, [loadData])

  useEffect(() => { if (active) loadData() }, [active])

  async function handleChangePassword() {
    if (!newPassword || !currentPassword) {
      toast.error('Please fill in all password fields')
      return
    }
    if (newPassword !== confirmPassword) {
      toast.error('New passwords do not match')
      return
    }
    if (newPassword.length < 8) {
      toast.error('Password must be at least 8 characters')
      return
    }
    setChangingPassword(true)
    try {
      await changePassword(currentPassword, newPassword)
      toast.success('Password changed successfully')
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
    } catch {
      toast.error('Failed to change password')
    } finally {
      setChangingPassword(false)
    }
  }

  async function handleCopyApiKey() {
    try {
      await navigator.clipboard.writeText(apiKey)
      toast.success('API key copied to clipboard')
    } catch {
      toast.error('Failed to copy to clipboard')
    }
  }

  async function handleLogout() {
    try {
      await logout()
      window.location.href = '/login'
    } catch {
      toast.error('Failed to log out')
    }
  }

  if (!me) {
    return <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">Loading...</div>
  }

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 py-4 sm:py-6 space-y-5">
      {/* Profile */}
      <SectionCard title="Profile">
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">Username</Label>
            <Input value={me.username} readOnly className="bg-muted/50 border-border/40" />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">Display Name</Label>
            <Input value={me.display_name} readOnly className="bg-muted/50 border-border/40" />
          </div>
        </div>
      </SectionCard>

      {/* Change Password */}
      <SectionCard title="Change Password">
        <div className="space-y-1.5">
          <Label className="text-xs text-muted-foreground">Current Password</Label>
          <Input
            type="password"
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
            className="bg-muted/50 border-border/40"
          />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">New Password</Label>
            <Input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              className="bg-muted/50 border-border/40"
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">Confirm New Password</Label>
            <Input
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              className="bg-muted/50 border-border/40"
            />
          </div>
        </div>
        <div className="flex justify-end">
          <Button onClick={handleChangePassword} disabled={changingPassword} size="sm">
            {changingPassword ? 'Changing...' : 'Change Password'}
          </Button>
        </div>
      </SectionCard>

      {/* API Key */}
      <SectionCard title="API Key">
        <p className="text-xs text-muted-foreground">Use this key for programmatic access (scripts, Telegram bot, etc).</p>
        <div className="flex gap-2">
          <Input value={apiKey} readOnly className="bg-muted/50 border-border/40 font-mono text-xs" />
          <Button variant="outline" size="sm" onClick={handleCopyApiKey} className="shrink-0 gap-2">
            <Copy className="h-4 w-4" /> Copy
          </Button>
        </div>
      </SectionCard>

      {/* Logout */}
      <div className="flex justify-end">
        <Button variant="outline" size="sm" onClick={handleLogout} className="gap-2 text-destructive hover:text-destructive">
          <LogOut className="h-4 w-4" /> Log Out
        </Button>
      </div>

      <div className="h-4" />
    </div>
  )
}
