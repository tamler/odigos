import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PasswordInput } from '@/components/PasswordInput'
import { login, setup, changePassword, webauthnLoginBegin, webauthnLoginComplete } from '@/lib/auth'

interface Props {
  setupRequired: boolean
  mustChangePassword: boolean
  onAuth: () => void
}

function base64urlToBuffer(base64url: string): ArrayBuffer {
  const base64 = base64url.replace(/-/g, '+').replace(/_/g, '/')
  const pad = base64.length % 4 === 0 ? '' : '='.repeat(4 - (base64.length % 4))
  const binary = atob(base64 + pad)
  return Uint8Array.from(binary, c => c.charCodeAt(0)).buffer
}

function bufferToBase64url(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer)
  let binary = ''
  bytes.forEach(b => binary += String.fromCharCode(b))
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '')
}

const EMAIL_RE = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/

export default function LoginPrompt({ setupRequired, mustChangePassword, onAuth }: Props) {
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmNewPassword, setConfirmNewPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await login(username, password)
      onAuth()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  async function handleSetup(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    if (!EMAIL_RE.test(email)) {
      setError('Enter a valid email address')
      return
    }
    if (password.length < 8) {
      setError('Password must be at least 8 characters')
      return
    }
    if (password !== confirmPassword) {
      setError('Passwords do not match')
      return
    }
    setLoading(true)
    try {
      await setup(username, email, password)
      await login(username, password)
      onAuth()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Setup failed')
    } finally {
      setLoading(false)
    }
  }

  async function handleChangePassword(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    if (newPassword !== confirmNewPassword) {
      setError('Passwords do not match')
      return
    }
    setLoading(true)
    try {
      await changePassword(currentPassword, newPassword)
      onAuth()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to change password')
    } finally {
      setLoading(false)
    }
  }

  async function handleBiometricLogin() {
    setError('')
    setLoading(true)
    try {
      const options = await webauthnLoginBegin()
      const publicKey: PublicKeyCredentialRequestOptions = {
        challenge: base64urlToBuffer(options.challenge),
        timeout: options.timeout,
        rpId: options.rpId,
        allowCredentials: (options.allowCredentials || []).map((c: any) => ({
          id: base64urlToBuffer(c.id),
          type: c.type,
          transports: c.transports,
        })),
        userVerification: options.userVerification,
      }
      const assertion = await navigator.credentials.get({ publicKey }) as PublicKeyCredential
      if (!assertion) throw new Error('No credential returned')
      const assertionResponse = assertion.response as AuthenticatorAssertionResponse
      const credential = {
        id: assertion.id,
        rawId: bufferToBase64url(assertion.rawId),
        type: assertion.type,
        response: {
          authenticatorData: bufferToBase64url(assertionResponse.authenticatorData),
          clientDataJSON: bufferToBase64url(assertionResponse.clientDataJSON),
          signature: bufferToBase64url(assertionResponse.signature),
          userHandle: assertionResponse.userHandle ? bufferToBase64url(assertionResponse.userHandle) : null,
        },
      }
      await webauthnLoginComplete(credential)
      onAuth()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Biometric login failed')
    } finally {
      setLoading(false)
    }
  }

  if (mustChangePassword) {
    return (
      <div className="flex items-center justify-center h-screen bg-background">
        <Card className="w-full max-w-sm">
          <CardHeader>
            <CardTitle>Change Password</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleChangePassword} className="space-y-4">
              <div className="space-y-2">
                <Label>Current Password</Label>
                <PasswordInput
                  value={currentPassword}
                  onChange={(e) => { setCurrentPassword(e.target.value); setError('') }}
                  autoFocus
                />
              </div>
              <div className="space-y-2">
                <Label>New Password</Label>
                <PasswordInput
                  value={newPassword}
                  onChange={(e) => { setNewPassword(e.target.value); setError('') }}
                />
              </div>
              <div className="space-y-2">
                <Label>Confirm New Password</Label>
                <PasswordInput
                  value={confirmNewPassword}
                  onChange={(e) => { setConfirmNewPassword(e.target.value); setError('') }}
                />
              </div>
              {error && <p className="text-sm text-destructive">{error}</p>}
              <Button type="submit" className="w-full" disabled={loading || !currentPassword || !newPassword || !confirmNewPassword}>
                {loading ? 'Changing...' : 'Change Password'}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    )
  }

  if (setupRequired) {
    return (
      <div className="flex items-center justify-center h-screen bg-background">
        <Card className="w-full max-w-sm">
          <CardHeader>
            <CardTitle>Create Account</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSetup} className="space-y-4">
              <div className="space-y-2">
                <Label>Username</Label>
                <Input
                  value={username}
                  onChange={(e) => { setUsername(e.target.value); setError('') }}
                  autoFocus
                  autoComplete="username"
                />
              </div>
              <div className="space-y-2">
                <Label>Email</Label>
                <Input
                  type="email"
                  value={email}
                  onChange={(e) => { setEmail(e.target.value); setError('') }}
                  autoComplete="email"
                  placeholder="you@example.com"
                />
              </div>
              <div className="space-y-2">
                <Label>Password</Label>
                <PasswordInput
                  value={password}
                  onChange={(e) => { setPassword(e.target.value); setError('') }}
                  autoComplete="new-password"
                />
              </div>
              <div className="space-y-2">
                <Label>Confirm Password</Label>
                <PasswordInput
                  value={confirmPassword}
                  onChange={(e) => { setConfirmPassword(e.target.value); setError('') }}
                  autoComplete="new-password"
                />
              </div>
              {error && <p className="text-sm text-destructive">{error}</p>}
              <Button type="submit" className="w-full" disabled={loading || !username || !email || !password || !confirmPassword}>
                {loading ? 'Creating...' : 'Create Account'}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="flex items-center justify-center h-screen bg-background">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Sign In</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleLogin} className="space-y-4">
            <div className="space-y-2">
              <Label>Username</Label>
              <Input
                value={username}
                onChange={(e) => { setUsername(e.target.value); setError('') }}
                autoFocus
              />
            </div>
            <div className="space-y-2">
              <Label>Password</Label>
              <PasswordInput
                value={password}
                onChange={(e) => { setPassword(e.target.value); setError('') }}
              />
            </div>
            {error && <p className="text-sm text-destructive">{error}</p>}
            <Button type="submit" className="w-full" disabled={loading || !username || !password}>
              {loading ? 'Signing in...' : 'Sign In'}
            </Button>
            {typeof window !== 'undefined' && window.PublicKeyCredential && (
              <div className="text-center pt-1">
                <button
                  type="button"
                  onClick={handleBiometricLogin}
                  disabled={loading}
                  className="text-xs text-muted-foreground hover:text-foreground transition-colors"
                >
                  Sign in with biometrics
                </button>
              </div>
            )}
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
