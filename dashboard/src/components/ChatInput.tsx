import { useState, useRef, useCallback } from 'react'
import { Button } from '@/components/ui/button'
import { Send, Paperclip, Mic, Volume2 } from 'lucide-react'
import { uploadFile } from '@/lib/api'

interface Props {
  onSend: (content: string, attachments?: { id: string; filename: string }[]) => void
  disabled: boolean
  hasSTT: boolean
  hasTTS: boolean
}

export default function ChatInput({ onSend, disabled, hasSTT, hasTTS }: Props) {
  const [input, setInput] = useState('')
  const [attachments, setAttachments] = useState<{ id: string; filename: string }[]>([])
  const [uploading, setUploading] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const handleSend = useCallback(() => {
    const trimmed = input.trim()
    if (!trimmed && attachments.length === 0) return
    onSend(trimmed, attachments.length > 0 ? attachments : undefined)
    setInput('')
    setAttachments([])
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
  }, [input, attachments, onSend])

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  async function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const files = e.target.files
    if (!files?.length) return
    setUploading(true)
    try {
      for (const file of Array.from(files)) {
        const result = await uploadFile(file)
        setAttachments((prev) => [...prev, { id: result.id, filename: result.filename }])
      }
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  function handleInput(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setInput(e.target.value)
    const el = e.target
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 200) + 'px'
  }

  return (
    <div className="border-t p-4">
      {attachments.length > 0 && (
        <div className="flex gap-2 mb-2 flex-wrap">
          {attachments.map((a) => (
            <span key={a.id} className="text-xs bg-muted px-2 py-1 rounded-full flex items-center gap-1">
              {a.filename}
              <button onClick={() => setAttachments((prev) => prev.filter((x) => x.id !== a.id))} className="hover:text-destructive">&times;</button>
            </span>
          ))}
        </div>
      )}
      <div className="flex items-end gap-2">
        <input ref={fileRef} type="file" multiple className="hidden" onChange={handleFileSelect} />
        <Button variant="ghost" size="icon" onClick={() => fileRef.current?.click()} disabled={disabled || uploading}>
          <Paperclip className="h-4 w-4" />
        </Button>
        {hasSTT && (
          <Button variant="ghost" size="icon" disabled={disabled}>
            <Mic className="h-4 w-4" />
          </Button>
        )}
        <textarea
          ref={textareaRef}
          value={input}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          placeholder="Send a message..."
          disabled={disabled}
          rows={1}
          className="flex-1 resize-none bg-muted rounded-xl px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring min-h-[44px] max-h-[200px]"
        />
        {hasTTS && (
          <Button variant="ghost" size="icon" disabled={disabled}>
            <Volume2 className="h-4 w-4" />
          </Button>
        )}
        <Button size="icon" onClick={handleSend} disabled={disabled || (!input.trim() && attachments.length === 0)}>
          <Send className="h-4 w-4" />
        </Button>
      </div>
    </div>
  )
}
