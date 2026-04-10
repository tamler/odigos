import { useState, useEffect, useRef, useCallback } from 'react'
import { ArrowUp, Mic, X } from 'lucide-react'
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
  prefill?: string | null
  onPrefillConsumed?: () => void
}

export function AgentInputBar({
  agentName,
  placeholder,
  pageContext,
  socketRef,
  connected,
  sttAvailable,
  prefill,
  onPrefillConsumed,
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

  useEffect(() => {
    if (prefill) {
      setInput(prefill)
      setFocused(true)
      onPrefillConsumed?.()
      inputRef.current?.focus()
    }
  }, [prefill, onPrefillConsumed])

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
  }, [socketRef])

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

  // Handle global Escape to close response or blur input
  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (response) setResponse(null)
        else setFocused(false)
      }
    }
    window.addEventListener('keydown', handleEsc)
    return () => window.removeEventListener('keydown', handleEsc)
  }, [response])

  return (
    <div className="relative w-full max-w-2xl mx-auto px-4 pb-6">
      {/* Response Area (G-W4) */}
      <div className={`overflow-hidden transition-all duration-500 ease-in-out ${response ? 'max-h-[500px] opacity-100 mb-4' : 'max-h-0 opacity-0'}`}>
        <div className="rounded-2xl border border-border/40 bg-background/95 backdrop-blur-md p-5 shadow-xl relative group/resp">
          <button 
            onClick={() => setResponse(null)}
            className="absolute top-3 right-3 p-2 lg:p-1 rounded-md opacity-100 lg:opacity-0 group-hover/resp:opacity-100 hover:bg-muted transition-all"
            title="Dismiss (Esc)"
          >
            <X className="h-4 w-4 lg:h-3.5 lg:w-3.5 text-muted-foreground" />
          </button>
          <div className="prose prose-sm dark:prose-invert max-w-none">
            <Markdown>{response || ''}</Markdown>
          </div>
          <div className="flex items-center justify-end mt-4 pt-3 border-t border-border/10 gap-3">
            <Button 
              size="sm" 
              variant="ghost"
              className="h-11 lg:h-7 px-4 lg:px-3 text-[11px] font-bold text-muted-foreground hover:text-foreground"
              onClick={() => {
                navigate(`/`) 
              }}
            >
              Continue in chat
            </Button>
          </div>
        </div>
      </div>

      {/* Input Bar */}
      <div className={`rounded-2xl border transition-all duration-300 ${focused ? 'border-primary/40 bg-background shadow-2xl ring-4 ring-primary/5' : 'border-border/40 bg-muted/20 hover:border-border/60 hover:bg-muted/30 shadow-sm'}`}>
        {!focused ? (
          <div 
            className="flex items-center justify-between px-5 py-4 lg:py-3 cursor-pointer group min-h-[44px]"
            onClick={() => setFocused(true)}
          >
            <div className="flex items-center gap-3 overflow-hidden">
              <div className="h-6 w-6 bg-primary/10 rounded-lg flex items-center justify-center shrink-0 group-hover:bg-primary/20 transition-colors">
                <span className="text-[10px] font-black text-primary">{(agentName || 'O')[0]}</span>
              </div>
              <span className="text-sm text-muted-foreground/80 font-medium truncate italic">{placeholder || `Ask ${agentName}...`} <span className="ml-2 text-[10px] not-italic opacity-0 lg:group-hover:opacity-100 transition-opacity font-bold uppercase tracking-widest text-muted-foreground/40 hidden lg:inline">(Press /)</span></span>
            </div>
            {sttAvailable && <Mic className="h-4 w-4 text-muted-foreground/40 group-hover:text-primary transition-colors" />}
          </div>
        ) : (
          <div className="flex flex-col">
            <div className="flex items-center gap-2 px-4 pt-3">
              <textarea
                ref={inputRef}
                value={input}
                onChange={e => {
                  setInput(e.target.value)
                  // Auto-resize
                  e.target.style.height = 'auto'
                  e.target.style.height = `${Math.min(e.target.scrollHeight, 200)}px`
                }}
                onKeyDown={e => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    send()
                  }
                }}
                placeholder={placeholder || `What's on your mind, ${agentName}?`}
                className="flex-1 bg-transparent border-none resize-none text-base lg:text-sm focus:outline-none min-h-[44px] lg:min-h-[40px] py-2 lg:py-1 custom-scrollbar"
                rows={1}
              />
            </div>
            <div className="flex items-center justify-between px-3 pb-2">
              <div className="flex items-center">
                {sttAvailable && (
                  <Button variant="ghost" size="icon" className="h-11 w-11 lg:h-8 lg:w-8 text-muted-foreground hover:text-primary"
                    onClick={() => { window.location.href = '/' }}
                    title="Open voice mode in chat"
                  >
                    <Mic className="h-5 w-5 lg:h-4 lg:w-4" />
                  </Button>
                )}
              </div>
              <div className="flex items-center gap-1">
                <Button 
                  variant="ghost" 
                  size="sm" 
                  className="h-11 lg:h-8 px-4 lg:px-3 text-[11px] font-bold text-muted-foreground"
                  onClick={() => setFocused(false)}
                >
                  Close
                </Button>
                <Button 
                  size="icon" 
                  className="h-11 w-11 lg:h-8 lg:w-8 rounded-xl shadow-lg shadow-primary/20"
                  disabled={!input.trim() || waiting}
                  onClick={send}
                >
                  {waiting ? (
                    <div className="h-3 w-3 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  ) : (
                    <ArrowUp className="h-5 w-5 lg:h-4 lg:w-4" />
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
