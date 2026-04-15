import { get, post } from './api'

export async function getAuthStatus(): Promise<{
  setup_required: boolean
  authenticated: boolean
  must_change_password: boolean
}> {
  return get('/api/auth/status')
}

export async function login(username: string, password: string): Promise<{ must_change_password: boolean }> {
  return post('/api/auth/login', { username, password })
}

export async function setup(username: string, email: string, password: string): Promise<void> {
  await post('/api/auth/setup', { username, email, password })
}

export async function logout(): Promise<void> {
  await post('/api/auth/logout')
  window.location.href = '/'
}

export async function webauthnRegisterBegin(): Promise<any> {
  return post('/api/webauthn/register/begin')
}

export async function webauthnRegisterComplete(credential: any): Promise<void> {
  await post('/api/webauthn/register/complete', { credential })
}

export async function webauthnLoginBegin(): Promise<any> {
  return post('/api/webauthn/login/begin')
}

export async function webauthnLoginComplete(credential: any): Promise<void> {
  await post('/api/webauthn/login/complete', { credential })
}

export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  await post('/api/auth/change-password', { current_password: currentPassword, new_password: newPassword })
}
