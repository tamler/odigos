import { useEffect, useRef, useState, useCallback } from 'react'
import { ChatSocket } from '@/lib/ws'
import { toast } from 'sonner'
import { ArrowUp } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  PromptInput,
  PromptInputTextarea,
  PromptInputActions,
  PromptInputAction,
} from '@/components/ui/prompt-input'
import { Message, MessageContent } from '@/components/ui/message'
import {
  ChatContainerRoot,
  ChatContainerContent,
  ChatContainerScrollAnchor,
} from '@/components/ui/chat-container'
import { Markdown } from '@/components/ui/markdown'
import { Loader } from '@/components/ui/loader'

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  timestamp: string
}

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [connected, setConnected] = useState(false)
  const [thinking, setThinking] = useState(false)
  const [inputValue, setInputValue] = useState('')
  const socketRef = useRef<ChatSocket | null>(null)

  useEffect(() => {
    const socket = new ChatSocket(
      (msg) => {
        if (msg.type === 'connected') {
          toast.success('Connected to Odigos', { duration: 2000 })
        }
        if (msg.type === 'chat_response') {
          setThinking(false)
          setMessages((prev) => [...prev, {
            role: 'assistant',
            content: msg.content as string,
            timestamp: new Date().toISOString(),
          }])
        }
      },
      (isConnected) => {
        setConnected(isConnected)
        if (!isConnected) {
          toast.error('Disconnected from server', { duration: 5000 })
        }
      },
    )
    socket.connect()
    socketRef.current = socket
    return () => socket.disconnect()
  }, [])

  const handleSend = useCallback(() => {
    const content = inputValue.trim()
    if (!content) return
    setMessages((prev) => [...prev, {
      role: 'user',
      content,
      timestamp: new Date().toISOString(),
    }])
    setThinking(true)
    socketRef.current?.send('chat', { content })
    setInputValue('')
  }, [inputValue])

  return (
    <div className="flex-1 flex flex-col">
      {/* Header */}
      <div className="px-6 py-4">
        <h2 className="text-sm font-medium text-muted-foreground">New conversation</h2>
      </div>

      {/* Messages area */}
      <ChatContainerRoot className="flex-1">
        <ChatContainerContent className="py-4">
          <div className="max-w-3xl mx-auto px-6 space-y-6">
            {messages.length === 0 && !thinking && (
              <div className="flex items-center justify-center h-[60vh] text-muted-foreground text-sm">
                What can I help you with?
              </div>
            )}
            {messages.map((msg, i) => (
              <Message
                key={i}
                className={msg.role === 'user' ? 'justify-end' : 'justify-start'}
              >
                <MessageContent
                  className={
                    msg.role === 'user'
                      ? 'bg-primary text-primary-foreground max-w-[85%] rounded-2xl'
                      : 'bg-muted max-w-[85%] rounded-2xl'
                  }
                >
                  {msg.role === 'assistant' ? (
                    <Markdown>{msg.content}</Markdown>
                  ) : (
                    msg.content
                  )}
                </MessageContent>
              </Message>
            ))}
            {thinking && (
              <Message className="justify-start">
                <MessageContent className="bg-muted max-w-[85%] rounded-2xl">
                  <Loader variant="typing" />
                </MessageContent>
              </Message>
            )}
          </div>
          <ChatContainerScrollAnchor />
        </ChatContainerContent>
      </ChatContainerRoot>

      {/* Input area */}
      <div className="pb-6 px-6">
        <div className="max-w-3xl mx-auto">
          <PromptInput
            value={inputValue}
            onValueChange={setInputValue}
            onSubmit={handleSend}
            disabled={!connected}
            className="border-border/40 bg-muted/50"
          >
            <PromptInputTextarea placeholder="Send a message..." />
            <PromptInputActions className="justify-end px-2 pb-2">
              <PromptInputAction tooltip="Send message">
                <Button
                  variant="default"
                  size="icon"
                  className="h-8 w-8 rounded-full"
                  disabled={!connected || !inputValue.trim()}
                  onClick={handleSend}
                >
                  <ArrowUp className="h-4 w-4" />
                </Button>
              </PromptInputAction>
            </PromptInputActions>
          </PromptInput>
        </div>
      </div>
    </div>
  )
}
