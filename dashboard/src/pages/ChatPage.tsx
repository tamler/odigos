import { useEffect, useRef, useState, useCallback } from 'react'
import { useOutletContext, useSearchParams } from 'react-router-dom'
import { ChatSocket } from '@/lib/ws'
import { get, uploadFile } from '@/lib/api'
import { toast } from 'sonner'
import { ArrowUp, Paperclip, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Markdown } from '@/components/ui/markdown'
import { Loader } from '@/components/ui/loader'
import {
  ChatContainerRoot,
  ChatContainerContent,
  ChatContainerScrollAnchor,
} from '@/components/ui/chat-container'
import { FileUpload, FileUploadTrigger, FileUploadContent } from '@/components/ui/file-upload'

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  timestamp: string
  attachments?: { id: string; filename: string; size: number }[]
}

interface OutletCtx {
  activeConversationId: string | null
  setActiveId: (id: string | null) => void
  refreshConversations: () => void
  socketRef: React.MutableRefObject<ChatSocket | null>
  connected: boolean
}

export default function ChatPage() {
  const { activeConversationId, setActiveId, refreshConversations, socketRef, connected } = useOutletContext<OutletCtx>()
  const [searchParams, setSearchParams] = useSearchParams()
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [thinking, setThinking] = useState(false)
  const [inputValue, setInputValue] = useState('')
  const [pendingFiles, setPendingFiles] = useState<{ file: File; id?: string; uploading?: boolean }[]>([])
  const loadedConvRef = useRef<string | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Wire up message handler on the shared socket
  useEffect(() => {
    const socket = socketRef.current
    if (!socket) return

    socket.onMessage = (msg) => {
      if (msg.type === 'chat_response') {
        setThinking(false)
        setMessages((prev) => [...prev, {
          role: 'assistant',
          content: msg.content as string,
          timestamp: new Date().toISOString(),
        }])
      }
      if (msg.type === 'conversation_started' && msg.conversation_id) {
        const cid = msg.conversation_id as string
        setActiveId(cid)
        setSearchParams({ c: cid })
        refreshConversations()
      }
      if (msg.type === 'title_updated' && msg.conversation_id && msg.title) {
        refreshConversations()
      }
    }

    return () => {
      socket.onMessage = null
    }
  }, [socketRef, setActiveId, setSearchParams, refreshConversations])

  // Load conversation messages when switching
  useEffect(() => {
    const cid = searchParams.get('c') || activeConversationId
    if (!cid) {
      if (loadedConvRef.current !== null) {
        setMessages([])
        loadedConvRef.current = null
      }
      return
    }
    if (cid === loadedConvRef.current) return
    loadedConvRef.current = cid

    get<{ messages: { role: string; content: string; timestamp: string }[] }>(
      `/api/conversations/${cid}/messages`
    )
      .then((data) => {
        if (data?.messages) {
          setMessages(
            data.messages.map((m) => ({
              role: m.role as 'user' | 'assistant',
              content: m.content,
              timestamp: m.timestamp,
            }))
          )
        }
      })
      .catch(() => {})
  }, [activeConversationId, searchParams])

  // Auto-resize textarea
  useEffect(() => {
    const ta = textareaRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = Math.min(ta.scrollHeight, 200) + 'px'
  }, [inputValue])

  const handleFilesAdded = useCallback(async (files: File[]) => {
    const newEntries = files.map((file) => ({ file, uploading: true }))
    setPendingFiles((prev) => [...prev, ...newEntries])

    for (let i = 0; i < files.length; i++) {
      try {
        const result = await uploadFile(files[i])
        setPendingFiles((prev) =>
          prev.map((p) =>
            p.file === files[i] ? { ...p, id: result.id, uploading: false } : p
          )
        )
      } catch {
        toast.error(`Failed to upload ${files[i].name}`)
        setPendingFiles((prev) => prev.filter((p) => p.file !== files[i]))
      }
    }
  }, [])

  function removeFile(file: File) {
    setPendingFiles((prev) => prev.filter((p) => p.file !== file))
  }

  const handleSend = useCallback(() => {
    const content = inputValue.trim()
    if (!content && pendingFiles.length === 0) return

    const attachments = pendingFiles
      .filter((p) => p.id)
      .map((p) => ({ id: p.id!, filename: p.file.name, size: p.file.size }))

    setMessages((prev) => [...prev, {
      role: 'user',
      content,
      timestamp: new Date().toISOString(),
      attachments: attachments.length > 0 ? attachments : undefined,
    }])
    setThinking(true)

    socketRef.current?.send('chat', {
      content,
      conversation_id: activeConversationId || undefined,
      attachments: attachments.length > 0 ? attachments : undefined,
    })

    setInputValue('')
    setPendingFiles([])
  }, [inputValue, pendingFiles, activeConversationId, socketRef])

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  function formatFileSize(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  const canSend = connected && (inputValue.trim() || pendingFiles.length > 0)

  return (
    <FileUpload onFilesAdded={handleFilesAdded}>
      <div className="flex-1 flex flex-col h-full">
        {/* Drag overlay */}
        <FileUploadContent>
          <div className="rounded-xl border-2 border-dashed border-primary/50 bg-primary/5 p-12 text-center">
            <p className="text-lg font-medium text-primary">Drop files here</p>
            <p className="text-sm text-muted-foreground mt-1">Files will be uploaded and attached to your message</p>
          </div>
        </FileUploadContent>

        {/* Messages area */}
        <ChatContainerRoot className="flex-1">
          <ChatContainerContent>
            <div className="max-w-[52rem] w-full mx-auto px-4 py-6 space-y-6">
              {messages.length === 0 && !thinking && (
                <div className="flex items-center justify-center h-[60vh] text-muted-foreground text-base">
                  What can I help you with?
                </div>
              )}
              {messages.map((msg, i) => (
                <div key={i}>
                  {msg.role === 'user' ? (
                    /* User: right-aligned bubble */
                    <div className="flex justify-end">
                      <div className="max-w-[85%]">
                        <div className="rounded-3xl bg-muted/60 px-5 py-3">
                          <div className="text-sm text-foreground whitespace-pre-wrap leading-relaxed">{msg.content}</div>
                        </div>
                        {msg.attachments && msg.attachments.length > 0 && (
                          <div className="mt-1.5 flex justify-end gap-2 flex-wrap">
                            {msg.attachments.map((a) => (
                              <div key={a.id} className="text-xs text-muted-foreground flex items-center gap-1">
                                <Paperclip className="h-3 w-3" />
                                {a.filename} ({formatFileSize(a.size)})
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  ) : (
                    /* Assistant: left-aligned plain text */
                    <div className="text-sm text-foreground leading-relaxed">
                      <Markdown>{msg.content}</Markdown>
                    </div>
                  )}
                </div>
              ))}
              {thinking && (
                <div>
                  <Loader variant="typing" />
                </div>
              )}
            </div>
            <ChatContainerScrollAnchor />
          </ChatContainerContent>
        </ChatContainerRoot>

        {/* Input area */}
        <div className="pb-4 pt-2 px-4">
          <div className="max-w-[52rem] mx-auto">
            {/* Pending files */}
            {pendingFiles.length > 0 && (
              <div className="flex flex-wrap gap-2 pb-2">
                {pendingFiles.map((p, i) => (
                  <div
                    key={i}
                    className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-muted text-sm"
                  >
                    <Paperclip className="h-3 w-3 text-muted-foreground" />
                    <span className="truncate max-w-[200px]">{p.file.name}</span>
                    <span className="text-xs text-muted-foreground">{formatFileSize(p.file.size)}</span>
                    {p.uploading && <Loader variant="typing" size="sm" />}
                    <button onClick={() => removeFile(p.file)} className="text-muted-foreground hover:text-foreground">
                      <X className="h-3 w-3" />
                    </button>
                  </div>
                ))}
              </div>
            )}

            {/* Composer */}
            <div className="relative rounded-2xl border border-border/50 bg-muted/30 focus-within:border-border/80 transition-colors">
              <textarea
                ref={textareaRef}
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Send a message..."
                disabled={!connected}
                rows={1}
                className="w-full resize-none bg-transparent px-4 pt-3 pb-12 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none disabled:opacity-50"
              />
              <div className="absolute bottom-2 left-2 right-2 flex items-center justify-between">
                <FileUploadTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 rounded-lg text-muted-foreground hover:text-foreground"
                    disabled={!connected}
                  >
                    <Paperclip className="h-4 w-4" />
                  </Button>
                </FileUploadTrigger>
                <Button
                  size="icon"
                  className="h-8 w-8 rounded-lg"
                  disabled={!canSend}
                  onClick={handleSend}
                >
                  <ArrowUp className="h-4 w-4" />
                </Button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </FileUpload>
  )
}
