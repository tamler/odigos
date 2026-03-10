import { useState, useEffect, useRef, useCallback } from 'preact/hooks'
import { html } from '../lib/htm.js'
import { createWsConnection } from '../lib/ws.js'

export function ChatPage() {
  const [messages, setMessages] = useState([])
  const [waiting, setWaiting] = useState(false)
  const [connected, setConnected] = useState(false)
  const [input, setInput] = useState('')
  const scrollRef = useRef(null)
  const wsRef = useRef(null)

  useEffect(() => {
    const ws = createWsConnection((data) => {
      if (data.type === '_connected') setConnected(true)
      if (data.type === '_disconnected') setConnected(false)
      if (data.type === 'chat' || data.type === 'chat_response') {
        setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'assistant', content: data.content }])
        setWaiting(false)
      }
    })
    wsRef.current = ws
    return () => ws.close()
  }, [])

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, waiting])

  const handleSend = useCallback(() => {
    const text = input.trim()
    if (!text || !connected) return
    setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'user', content: text }])
    setInput('')
    setWaiting(true)
    wsRef.current?.sendChat(text)
  }, [input, connected])

  const handleKeyDown = useCallback((e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }, [handleSend])

  return html`
    <div class="chat-container">
      <div class="chat-header">
        <h2 style="font-size:18px;font-weight:600">Chat</h2>
        <span style="font-size:12px;display:flex;align-items:center">
          <span class="status-dot ${connected ? 'connected' : 'disconnected'}"></span>
          ${connected ? 'Connected' : 'Disconnected'}
        </span>
      </div>

      <div class="chat-messages" ref=${scrollRef}>
        ${messages.length === 0 && !waiting && html`
          <p style="text-align:center;color:var(--text-muted);margin-top:32px">
            Start a conversation...
          </p>
        `}
        ${messages.map(msg => html`
          <div class="message ${msg.role}" key=${msg.id}>
            <div class="bubble">${msg.content}</div>
          </div>
        `)}
        ${waiting && html`
          <div class="message thinking">
            <div class="bubble">Thinking...</div>
          </div>
        `}
      </div>

      <div class="chat-input-bar">
        <textarea
          value=${input}
          onInput=${(e) => setInput(e.target.value)}
          onKeyDown=${handleKeyDown}
          placeholder="Type a message..."
          disabled=${!connected}
          rows="1"
        />
        <button onClick=${handleSend} disabled=${!connected || !input.trim()}>
          Send
        </button>
      </div>
    </div>
  `
}
