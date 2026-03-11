import { useEffect, useRef, useState, useCallback } from 'react'
import { ChatSocket } from '@/lib/ws'
import { get } from '@/lib/api'
import ChatMessage from '@/components/ChatMessage'
import ChatInput from '@/components/ChatInput'

interface Message {
  role: 'user' | 'assistant'
  content: string
  timestamp: string
}

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([])
  const [connected, setConnected] = useState(false)
  const [thinking, setThinking] = useState(false)
  const [hasSTT, setHasSTT] = useState(false)
  const [hasTTS, setHasTTS] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const socketRef = useRef<ChatSocket | null>(null)

  useEffect(() => {
    get<{ plugins: { capabilities: string[] }[] }>('/api/plugins')
      .then((data) => {
        const caps = data.plugins.flatMap((p) => p.capabilities)
        setHasSTT(caps.includes('stt'))
        setHasTTS(caps.includes('tts'))
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    const socket = new ChatSocket(
      (msg) => {
        if (msg.type === 'chat_response') {
          setThinking(false)
          setMessages((prev) => [...prev, {
            role: 'assistant',
            content: msg.content as string,
            timestamp: new Date().toISOString(),
          }])
        }
      },
      setConnected,
    )
    socket.connect()
    socketRef.current = socket
    return () => socket.disconnect()
  }, [])

  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, thinking])

  const handleSend = useCallback((content: string, attachments?: { id: string; filename: string }[]) => {
    let displayContent = content
    if (attachments?.length) {
      const fileList = attachments.map((a) => a.filename).join(', ')
      displayContent = content ? `${content}\n\n[Attached: ${fileList}]` : `[Attached: ${fileList}]`
    }

    setMessages((prev) => [...prev, {
      role: 'user',
      content: displayContent,
      timestamp: new Date().toISOString(),
    }])
    setThinking(true)

    const msgContent = attachments?.length
      ? `${content}\n\n[Files: ${attachments.map((a) => `${a.filename} (${a.id})`).join(', ')}]`
      : content
    socketRef.current?.send('chat', { content: msgContent })
  }, [])

  return (
    <div className="flex-1 flex flex-col">
      <div className="border-b px-4 py-3 flex items-center justify-between">
        <h2 className="font-semibold">Chat</h2>
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <span className={`h-2 w-2 rounded-full ${connected ? 'bg-green-500' : 'bg-red-500'}`} />
          {connected ? 'Connected' : 'Disconnected'}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 && !thinking && (
          <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm h-full">
            Send a message to start chatting
          </div>
        )}
        {messages.map((msg, i) => (
          <ChatMessage key={i} role={msg.role} content={msg.content} timestamp={msg.timestamp} />
        ))}
        {thinking && (
          <div className="flex justify-start">
            <div className="bg-muted rounded-2xl px-4 py-3">
              <span className="animate-pulse">Thinking...</span>
            </div>
          </div>
        )}
        <div ref={scrollRef} />
      </div>

      <ChatInput
        onSend={handleSend}
        disabled={!connected}
        hasSTT={hasSTT}
        hasTTS={hasTTS}
      />
    </div>
  )
}
