import { useState, useEffect, useRef, useCallback } from 'react'
import { ArrowUp, Mic } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ChatSocket } from '@/lib/ws'
import { Markdown } from '@/components/ui/markdown'
import { useNavigate } from 'react-router-dom'

interface AgentInputBarProps {
  agentName: string
  placeholder?: string
  pageContext: Record<string, any>
  socketRef: React.MutableRefObject<ChatSocket | null>
  connected: boolean
  sttAvailable: boolean
  onResponse?: (content: string) => void
}

export function AgentInputBar({
  agentName,
  placeholder = "Ask about this workspace...",
  pageContext,
  socketRef,
  connected,
  sttAvailable,
}: AgentInputBarProps) {
  const [focused, setFocused] = useState(false)
  const [input, setInput] = useState('')
  const [response, setResponse] = useState<string | null>(null)
  const [waiting, setWaiting] = useState(false)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const navigate = useNavigate()

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === '/' && !['INPUT', 'TEXTAREA'].includes((e.target as HTMLElement).tagName)) {
        e.preventDefault()
        setFocused(true)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  useEffect(() => {
    if (focused) {
      inputRef.current?.focus()
    }
  }, [focused])

  // Listen for responses
  useEffect(() => {
    const socket = socketRef.current
    if (!socket) return

    const originalHandler = socket.onMessage
    socket.onMessage = (msg) => {
      if (originalHandler) originalHandler(msg)
      
      if (msg.type === 'chat_response') {
        setResponse(msg.content as string)
        setWaiting(false)
      }
    }

    return () => {
      socket.onMessage = originalHandler
    }
  }, [socketRef, waiting])

  const send = useCallback(() => {
    if (!input.trim() || !connected) return
    socketRef.current?.send('chat', {
      content: input,
      context: pageContext,
    })
    setInput('')
    setWaiting(true)
    setResponse(null)
  }, [input, connected, pageContext, socketRef])

  return (
    <div className="relative w-full max-w-2xl mx-auto px-4 pb-4">
      {/* Response Popover (G-W4) */}
      {response && (
        <div className="absolute bottom-full left-0 right-0 mx-4 mb-4 max-h-[400px] overflow-y-auto rounded-2xl border border-border/40 bg-background/95 backdrop-blur-md p-5 shadow-2xl animate-in slide-in-from-bottom-2 duration-300 z-50">
          <div className="prose prose-sm dark:prose-invert max-w-none">
            <Markdown>{response}</Markdown>
          </div>
          <div className="flex items-center justify-end mt-4 pt-3 border-t border-border/20 gap-3">
            <button 
              onClick={() => setResponse(null)} 
              className="text-xs font-semibold text-muted-foreground hover:text-foreground transition-colors"
            >
              Dismiss
            </button>
            <Button 
              size="sm" 
              variant="secondary"
              className="h-8 text-xs font-bold"
              onClick={() => {
                // Navigate to main chat
                navigate('/')
              }}
            >
              Continue in chat
            </Button>
          </div>
        </div>
      )}

      {/* Input Bar */}
      <div className={`rounded-2xl border transition-all duration-200 ${focused ? 'border-primary/50 bg-background shadow-lg ring-4 ring-primary/5' : 'border-border/40 bg-muted/30 hover:border-border/80'}`}>
        {!focused ? (
          <div 
            className="flex items-center justify-between px-4 py-3 cursor-pointer"
            onClick={() => setFocused(true)}
          >
            <div className="flex items-center gap-2 overflow-hidden">
              <span className="font-bold text-sm text-primary shrink-0">{agentName}</span>
              <span className="text-sm text-muted-foreground truncate">type / or click to ask...</span>
            </div>
            {sttAvailable && <Mic className="h-4 w-4 text-muted-foreground/60" />}
          </div>
        ) : (
          <div className="flex flex-col">
            <div className="flex items-center gap-2 px-4 pt-3">
              <textarea
                ref={inputRef}
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    send()
                  }
                  if (e.key === 'Escape') {
                    setFocused(false)
                  }
                }}
                placeholder={placeholder}
                className="flex-1 bg-transparent border-none resize-none text-sm focus:outline-none min-h-[40px] py-1"
                rows={1}
              />
            </div>
            <div className="flex items-center justify-between px-3 pb-2">
              <div className="flex items-center">
                {sttAvailable && (
                  <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground">
                    <Mic className="h-4 w-4" />
                  </Button>
                )}
              </div>
              <div className="flex items-center gap-2">
                <Button 
                  variant="ghost" 
                  size="sm" 
                  className="h-8 text-xs text-muted-foreground"
                  onClick={() => setFocused(false)}
                >
                  Cancel
                </Button>
                <Button 
                  size="icon" 
                  className="h-8 w-8 rounded-xl"
                  disabled={!input.trim() || waiting}
                  onClick={send}
                >
                  {waiting ? (
                    <div className="h-3 w-3 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  ) : (
                    <ArrowUp className="h-4 w-4" />
                  )}
                </Button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
