export async function getAuthStatus(): Promise<{
  setup_required: boolean
  authenticated: boolean
  must_change_password: boolean
}> {
  const res = await fetch('/api/auth/status')
  if (!res.ok) throw new Error('Failed to check auth status')
  return res.json()
}

export async function login(username: string, password: string): Promise<{ must_change_password: boolean }> {
  const res = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  if (res.status === 401) throw new Error('Invalid username or password')
  if (!res.ok) throw new Error('Login failed')
  return res.json()
}

export async function setup(username: string, password: string): Promise<void> {
  const res = await fetch('/api/auth/setup', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || 'Setup failed')
  }
}

export async function logout(): Promise<void> {
  await fetch('/api/auth/logout', { method: 'POST' })
  window.location.reload()
}

export async function webauthnRegisterBegin(): Promise<any> {
  const res = await fetch('/api/webauthn/register/begin', {
    method: 'POST',
    credentials: 'include',
  })
  if (!res.ok) throw new Error('Failed to start registration')
  return res.json()
}

export async function webauthnRegisterComplete(credential: any): Promise<void> {
  const res = await fetch('/api/webauthn/register/complete', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ credential }),
  })
  if (!res.ok) throw new Error('Failed to complete registration')
}

export async function webauthnLoginBegin(): Promise<any> {
  const res = await fetch('/api/webauthn/login/begin', {
    method: 'POST',
    credentials: 'include',
  })
  if (!res.ok) throw new Error('No passkeys registered')
  return res.json()
}

export async function webauthnLoginComplete(credential: any): Promise<void> {
  const res = await fetch('/api/webauthn/login/complete', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ credential }),
  })
  if (!res.ok) throw new Error('Biometric verification failed')
}

export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  const res = await fetch('/api/auth/change-password', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || 'Failed to change password')
  }
}
