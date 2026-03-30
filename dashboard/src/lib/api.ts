/**
 * Unified HTTP client — ALL requests go through this module.
 *
 * No raw fetch() or XMLHttpRequest anywhere else in the codebase.
 * CSRF, auth, error handling, and headers are managed in one place.
 */

const BASE = ''  // Same origin

const CSRF_HEADER = 'X-Requested-With'
const CSRF_VALUE = 'XMLHttpRequest'

function jsonHeaders(): HeadersInit {
  return {
    'Content-Type': 'application/json',
    [CSRF_HEADER]: CSRF_VALUE,
  }
}

function csrfHeaders(): HeadersInit {
  return { [CSRF_HEADER]: CSRF_VALUE }
}

function handleError(res: Response): void {
  if (res.status === 401 || res.status === 403) {
    throw new Error('unauthorized')
  }
  if (!res.ok) throw new Error(`API error: ${res.status}`)
}

// ── JSON requests ──────────────────────────────────────────────

export async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { headers: jsonHeaders() })
  handleError(res)
  return res.json()
}

export async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: jsonHeaders(),
    body: body ? JSON.stringify(body) : undefined,
  })
  handleError(res)
  return res.json()
}

export async function patch<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'PATCH',
    headers: jsonHeaders(),
    body: body ? JSON.stringify(body) : undefined,
  })
  handleError(res)
  return res.json()
}

export async function put<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'PUT',
    headers: jsonHeaders(),
    body: body ? JSON.stringify(body) : undefined,
  })
  handleError(res)
  return res.json()
}

export async function del<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'DELETE',
    headers: jsonHeaders(),
  })
  handleError(res)
  return res.json()
}

// ── FormData requests (uploads, audio) ─────────────────────────

export async function postForm<T>(path: string, formData: FormData): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: csrfHeaders(),  // No Content-Type -- browser sets multipart boundary
    body: formData,
  })
  handleError(res)
  return res.json()
}

export async function postFormRaw(path: string, formData: FormData): Promise<Response> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: csrfHeaders(),
    body: formData,
  })
  return res  // Caller handles response (e.g. check res.ok)
}

// ── Binary/blob requests (audio speak, file download) ──────────

export async function getBlob(path: string): Promise<Blob> {
  const res = await fetch(`${BASE}${path}`, {
    headers: csrfHeaders(),
  })
  handleError(res)
  return res.blob()
}

// ── File upload with progress ──────────────────────────────────

export async function uploadFile(
  file: File,
  onProgress?: (progress: number) => void,
): Promise<{ id: string; filename: string; size: number }> {
  if (onProgress) {
    // Use XHR for progress tracking (fetch doesn't support upload progress)
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      xhr.open('POST', `${BASE}/api/upload`)
      xhr.setRequestHeader(CSRF_HEADER, CSRF_VALUE)

      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) {
          onProgress(Math.round((e.loaded / e.total) * 100))
        }
      }

      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try { resolve(JSON.parse(xhr.responseText)) }
          catch { reject(new Error('Invalid JSON response')) }
        } else {
          reject(new Error(`Upload error: ${xhr.status}`))
        }
      }

      xhr.onerror = () => reject(new Error('Network error during upload'))

      const form = new FormData()
      form.append('file', file)
      xhr.send(form)
    })
  }

  // No progress needed -- use fetch (simpler, covered by CSRF)
  const form = new FormData()
  form.append('file', file)
  return postForm('/api/upload', form)
}
