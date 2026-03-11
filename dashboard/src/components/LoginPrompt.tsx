import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { setApiKey } from '@/lib/auth'

interface Props {
  onLogin: () => void
}

export default function LoginPrompt({ onLogin }: Props) {
  const [key, setKey] = useState('')
  const [error, setError] = useState('')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!key.trim()) return
    setApiKey(key.trim())
    try {
      const res = await fetch('/api/settings', {
        headers: { Authorization: `Bearer ${key.trim()}` },
      })
      if (res.ok) {
        onLogin()
      } else {
        setError('Invalid API key')
      }
    } catch {
      setError('Connection failed')
    }
  }

  return (
    <div className="flex items-center justify-center h-screen bg-background">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Sign In</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label>API Key</Label>
              <Input
                type="password"
                value={key}
                onChange={(e) => { setKey(e.target.value); setError('') }}
                placeholder="Enter your API key"
                autoFocus
              />
            </div>
            {error && <p className="text-sm text-destructive">{error}</p>}
            <Button type="submit" className="w-full" disabled={!key.trim()}>Sign In</Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
