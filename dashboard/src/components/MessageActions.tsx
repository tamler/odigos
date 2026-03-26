import { useState } from 'react'
import { Copy, Volume2, Flag, RotateCcw, Pencil, Check, X } from 'lucide-react'
import { toast } from 'sonner'
import { post } from '@/lib/api'
import { ChatSocket } from '@/lib/ws'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'

interface MessageActionsProps {
  role: 'user' | 'assistant'
  content: string
  messageIndex: number
  conversationId: string
  previousUserMessage?: string  // for retry (assistant messages only)
  isStreaming: boolean          // disable retry while streaming
  ttsAvailable: boolean        // hide speak if TTS disabled
  socket: ChatSocket | null    // ChatSocket from '@/lib/ws' (socketRef.current)
  onEdit: (index: number, content: string) => void
  playTTS: (text: string) => void
}

export function MessageActions({
  role,
  content,
  messageIndex,
  conversationId,
  previousUserMessage,
  isStreaming,
  ttsAvailable,
  socket,
  onEdit,
  playTTS,
}: MessageActionsProps) {
  const [isEditing, setIsEditing] = useState(false)
  const [editValue, setEditValue] = useState(content)
  const [isSpeaking, setIsSpeaking] = useState(false)

  const handleCopy = () => {
    navigator.clipboard.writeText(content)
    toast.success('Copied to clipboard')
  }

  const handleReport = async (reason: string) => {
    try {
      await post(`/api/conversations/${conversationId}/report`, {
        message_index: messageIndex,
        reason,
        message_content: content,
      })
      toast.success('Report submitted')
    } catch {
      toast.error('Failed to submit report')
    }
  }

  const handleRetry = () => {
    if (!previousUserMessage || isStreaming) return
    socket?.send('retry', {
      content: previousUserMessage,
      conversation_id: conversationId,
    })
  }

  const handleSaveEdit = () => {
    if (editValue.trim() && editValue !== content) {
      onEdit(messageIndex, editValue)
    }
    setIsEditing(false)
  }

  if (isEditing) {
    return (
      <div className="mt-2 space-y-2 w-full animate-in fade-in slide-in-from-top-1 duration-200">
        <Textarea
          value={editValue}
          onChange={(e) => setEditValue(e.target.value)}
          className="min-h-[80px] text-sm bg-background border-border/60"
          autoFocus
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              handleSaveEdit()
            }
            if (e.key === 'Escape') {
              setIsEditing(false)
            }
          }}
        />
        <div className="flex justify-end gap-2">
          <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => setIsEditing(false)}>
            <X className="h-3.5 w-3.5 mr-1" /> Cancel
          </Button>
          <Button size="sm" className="h-7 text-xs" onClick={handleSaveEdit}>
            <Check className="h-3.5 w-3.5 mr-1" /> Save
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className="opacity-0 group-hover/msg:opacity-100 transition-opacity flex items-center gap-2 mt-1">
      <button
        onClick={handleCopy}
        className="text-muted-foreground hover:text-foreground transition-colors p-0.5"
        title="Copy"
        aria-label="Copy message"
      >
        <Copy className="h-4 w-4" />
      </button>
      
      {role === 'assistant' && ttsAvailable && (
        <button
          onClick={() => {
            if (isSpeaking) return
            setIsSpeaking(true)
            playTTS(content)
            // Debounce: prevent rapid double-clicks. The actual audio
            // lifecycle is managed by AppLayout's currentAudioRef.
            setTimeout(() => setIsSpeaking(false), 500)
          }}
          disabled={isSpeaking}
          className={`text-muted-foreground hover:text-foreground transition-colors p-0.5 ${isSpeaking ? 'opacity-50' : ''}`}
          title="Speak"
          aria-label="Speak message"
        >
          <Volume2 className="h-4 w-4" />
        </button>
      )}

      {role === 'assistant' && (
        <DropdownMenu>
          <DropdownMenuTrigger>
            <button
              className="text-muted-foreground hover:text-foreground transition-colors p-0.5"
              title="Report"
              aria-label="Report message"
            >
              <Flag className="h-4 w-4" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-32">
            <DropdownMenuItem onClick={() => handleReport('wrong')}>Wrong</DropdownMenuItem>
            <DropdownMenuItem onClick={() => handleReport('unhelpful')}>Unhelpful</DropdownMenuItem>
            <DropdownMenuItem onClick={() => handleReport('harmful')}>Harmful</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      )}

      {role === 'assistant' && previousUserMessage && (
        <button
          onClick={handleRetry}
          disabled={isStreaming}
          className={`text-muted-foreground hover:text-foreground transition-colors p-0.5 ${isStreaming ? 'opacity-50 cursor-not-allowed' : ''}`}
          title="Retry"
          aria-label="Retry generation"
        >
          <RotateCcw className="h-4 w-4" />
        </button>
      )}

      {role === 'user' && (
        <button
          onClick={() => {
            setEditValue(content)
            setIsEditing(true)
          }}
          className="text-muted-foreground hover:text-foreground transition-colors p-0.5"
          title="Edit"
          aria-label="Edit message"
        >
          <Pencil className="h-4 w-4" />
        </button>
      )}
    </div>
  )
}
