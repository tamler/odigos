import { get } from '@/lib/api'

interface CachedMessages {
  messages: unknown[]
  total: number
  fetchedAt: number
}

const cache = new Map<string, CachedMessages>()
const inflight = new Set<string>()

const CACHE_TTL_MS = 60_000

export function getCachedMessages(conversationId: string): CachedMessages | undefined {
  const entry = cache.get(conversationId)
  if (!entry) return undefined
  if (Date.now() - entry.fetchedAt > CACHE_TTL_MS) {
    cache.delete(conversationId)
    return undefined
  }
  return entry
}

export function prefetchMessages(conversationId: string): void {
  if (cache.has(conversationId) && Date.now() - cache.get(conversationId)!.fetchedAt < CACHE_TTL_MS) return
  if (inflight.has(conversationId)) return

  inflight.add(conversationId)
  get<{ messages: unknown[]; total: number }>(`/api/conversations/${conversationId}/messages?limit=50`)
    .then((data) => {
      cache.set(conversationId, {
        messages: data.messages,
        total: data.total,
        fetchedAt: Date.now(),
      })
    })
    .catch(() => {})
    .finally(() => {
      inflight.delete(conversationId)
    })
}
