import { useState, useEffect, useRef, memo } from 'react'
import { MessageCircle, X, Send, Mic, ChevronDown } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { ChatSocket } from '@/lib/ws'
import { Markdown } from '@/components/ui/markdown'
import { PageContext } from '@/hooks/usePageContext'
import { AssistantConfig } from '@/layouts/AppLayout'
import type { ChatMessage } from '@/layouts/AppLayout'

interface FloatingBubbleProps {
  socketRef: React.MutableRefObject<ChatSocket | null>
  connected: boolean
  activeConversationId: string | null
  messages: ChatMessage[]
  onSend: (content: string, context?: Record<string, any>) => void
  pageContext: PageContext
  assistantConfig: AssistantConfig
  agentName: string
  ttsAvailable: boolean
  sttAvailable: boolean
  playTTS: (text: string) => void
}

export const FloatingBubble = memo(({
  socketRef: _socketRef,
  connected: _connected,
  activeConversationId: _activeConversationId,
  messages,
  onSend,
  pageContext,
  assistantConfig,
  agentName,
  ttsAvailable: _ttsAvailable,
  sttAvailable,
  playTTS: _playTTS,
}: FloatingBubbleProps) => {
  // These will be used when full bubble features are wired
  void _socketRef; void _connected; void _activeConversationId; void _ttsAvailable; void _playTTS
  const [expanded, setExpanded] = useState(false)
  const [inputValue, setInputValue] = useState('')
  const [unreadCount, setUnreadCount] = useState(0)
  const [position, setPosition] = useState(() => {
    const saved = localStorage.getItem('odigos-bubble-pos')
    return saved ? JSON.parse(saved) : { x: 0, y: 0 }
  })
  const [isDragging, setIsDragging] = useState(false)
  const dragStart = useRef({ x: 0, y: 0 })
  const scrollRef = useRef<HTMLDivElement>(null)
  const lastMessageCount = useRef(messages.length)

  // Auto-scroll to bottom
  useEffect(() => {
    if (expanded) {
      setTimeout(() => {
        const viewport = scrollRef.current?.querySelector('[data-radix-scroll-area-viewport]')
        if (viewport) viewport.scrollTop = viewport.scrollHeight
      }, 100)
    }
  }, [expanded, messages])

  // Track unread messages
  useEffect(() => {
    if (!expanded && messages.length > lastMessageCount.current) {
      const newMsgs = messages.slice(lastMessageCount.current)
      const assistantMsgs = newMsgs.filter(m => m.role === 'assistant')
      if (assistantMsgs.length > 0) {
        setUnreadCount(prev => prev + assistantMsgs.length)
      }
    }
    lastMessageCount.current = messages.length
  }, [messages, expanded])

  useEffect(() => {
    if (expanded) setUnreadCount(0)
  }, [expanded])

  const handleMouseDown = (e: React.MouseEvent) => {
    if (expanded) return
    setIsDragging(true)
    dragStart.current = { x: e.clientX - position.x, y: e.clientY - position.y }
  }

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isDragging) return
      const newX = e.clientX - dragStart.current.x
      const newY = e.clientY - dragStart.current.y
      setPosition({ x: newX, y: newY })
    }
    const handleMouseUp = () => {
      if (isDragging) {
        setIsDragging(false)
        localStorage.setItem('odigos-bubble-pos', JSON.stringify(position))
      }
    }
    if (isDragging) {
      window.addEventListener('mousemove', handleMouseMove)
      window.addEventListener('mouseup', handleMouseUp)
    }
    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
    }
  }, [isDragging, position])

  const handleSend = () => {
    if (!inputValue.trim()) return
    onSend(inputValue, pageContext)
    setInputValue('')
  }

  const posStyle = assistantConfig.position === 'bottom-right' 
    ? { bottom: '16px', right: '16px' }
    : { bottom: '16px', left: '16px' }

  const panelPosClass = assistantConfig.position === 'bottom-right'
    ? 'right-0 origin-bottom-right scale-in-from-bottom-right'
    : 'left-0 origin-bottom-left scale-in-from-bottom-left'

  const transform = `translate(${position.x}px, ${position.y}px)`

  if (!assistantConfig.enabled) return null

  return (
    <div 
      className="fixed z-[100] transition-transform duration-75 select-none"
      style={{ ...posStyle, transform }}
    >
      {/* Expanded Panel */}
      {expanded && (
        <div className={`absolute bottom-16 w-[calc(100vw-32px)] sm:w-[320px] max-h-[450px] bg-background border border-border/60 rounded-2xl shadow-2xl flex flex-col overflow-hidden animate-in duration-200 ease-out ${panelPosClass}`}>
          {/* Header */}
          <header className="flex items-center justify-between px-4 py-3 border-b border-border/40 bg-muted/5">
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
              <span className="text-sm font-bold">{agentName}</span>
            </div>
            <button 
              onClick={() => setExpanded(false)}
              className="text-muted-foreground hover:text-foreground transition-colors"
            >
              <ChevronDown className="h-4 w-4" />
            </button>
          </header>

          {/* Transcript */}
          <ScrollArea ref={scrollRef} className="flex-1 min-h-[200px] bg-background/50">
            <div className="p-4 space-y-4">
              {messages.length === 0 && (
                <p className="text-xs text-muted-foreground text-center py-8">
                  How can I help you with this {pageContext.page}?
                </p>
              )}
              {messages.slice(-20).map((msg, i) => (
                <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div className={`max-w-[85%] rounded-2xl px-3 py-2 text-xs shadow-sm ${
                    msg.role === 'user' ? 'bg-primary text-primary-foreground' : 'bg-muted/50 border border-border/20'
                  }`}>
                    <Markdown>{msg.content}</Markdown>
                  </div>
                </div>
              ))}
            </div>
          </ScrollArea>

          {/* Footer */}
          <footer className="p-3 border-t border-border/40 bg-muted/5 space-y-2">
            <div className="flex gap-2">
              {assistantConfig.text_input && (
                <div className="relative flex-1">
                  <input
                    type="text"
                    value={inputValue}
                    onChange={(e) => setInputValue(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleSend()}
                    placeholder="Ask anything..."
                    className="w-full bg-background border border-border/40 rounded-xl px-3 py-2 text-xs focus:outline-none focus:ring-1 focus:ring-primary/50 transition-all"
                  />
                  <button 
                    onClick={handleSend}
                    disabled={!inputValue.trim()}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-primary disabled:opacity-30"
                  >
                    <Send className="h-3.5 w-3.5" />
                  </button>
                </div>
              )}
              {assistantConfig.voice_input && sttAvailable && (
                <Button size="icon" variant="ghost" className="h-8 w-8 rounded-xl shrink-0"
                  onClick={() => { window.location.href = '/' }}
                  title="Open voice mode in chat"
                >
                  <Mic className="h-4 w-4" />
                </Button>
              )}
            </div>
            <p className="text-[10px] text-muted-foreground text-center px-2 truncate">
              Context: {pageContext.page_title || pageContext.page}
            </p>
          </footer>
        </div>
      )}

      {/* Bubble Button */}
      <button
        onMouseDown={handleMouseDown}
        onClick={() => !isDragging && setExpanded(!expanded)}
        className={`relative h-12 w-12 rounded-full shadow-lg flex items-center justify-center transition-all duration-300 ${
          expanded 
            ? 'bg-background border border-border/60 text-foreground scale-90' 
            : 'bg-primary text-primary-foreground hover:scale-110 active:scale-95'
        } ${unreadCount > 0 && !expanded ? 'animate-pulse' : ''}`}
      >
        {expanded ? <X className="h-5 w-5" /> : <MessageCircle className="h-6 w-6" />}
        
        {unreadCount > 0 && !expanded && (
          <span className="absolute -top-1 -right-1 h-5 w-5 bg-red-500 text-white text-[10px] font-bold rounded-full flex items-center justify-center border-2 border-background shadow-sm">
            {unreadCount}
          </span>
        )}
      </button>
    </div>
  )
})

FloatingBubble.displayName = 'FloatingBubble'
