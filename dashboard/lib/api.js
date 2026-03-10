const BASE = '/api'

async function fetchJSON(path, init) {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`)
  return res.json()
}

export const api = {
  conversations: {
    list: (limit = 20, offset = 0) => fetchJSON(`/conversations?limit=${limit}&offset=${offset}`),
    get: (id) => fetchJSON(`/conversations/${encodeURIComponent(id)}`),
    messages: (id) => fetchJSON(`/conversations/${encodeURIComponent(id)}/messages`),
  },
  goals: () => fetchJSON('/goals'),
  todos: () => fetchJSON('/todos'),
  reminders: () => fetchJSON('/reminders'),
  budget: () => fetchJSON('/budget'),
  metrics: () => fetchJSON('/metrics'),
  plugins: () => fetchJSON('/plugins'),
  memory: {
    entities: () => fetchJSON('/memory/entities'),
    search: (q) => fetchJSON(`/memory/search?q=${encodeURIComponent(q)}`),
  },
  sendMessage: (content, conversationId) =>
    fetchJSON('/message', {
      method: 'POST',
      body: JSON.stringify({ content, conversation_id: conversationId }),
    }),
}
