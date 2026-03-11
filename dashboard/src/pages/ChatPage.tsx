import { useEffect, useRef, useState, useCallback } from 'react'
import { useOutletContext, useSearchParams } from 'react-router-dom'
import { ChatSocket } from '@/lib/ws'
import { get, uploadFile } from '@/lib/api'
import { toast } from 'sonner'
import { ArrowUp, Paperclip, X } from 'lucide-react'
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
}

export default function ChatPage() {
  const { activeConversationId, setActiveId, refreshConversations } = useOutletContext<OutletCtx>()
  const [searchParams, setSearchParams] = useSearchParams()
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [connected, setConnected] = useState(false)
  const [thinking, setThinking] = useState(false)
  const [inputValue, setInputValue] = useState('')
  const [pendingFiles, setPendingFiles] = useState<{ file: File; id?: string; uploading?: boolean }[]>([])
  const [conversationTitle, setConversationTitle] = useState<string | null>(null)
  const socketRef = useRef<ChatSocket | null>(null)
  const loadedConvRef = useRef<string | null>(null)

  // WebSocket connection
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
        // If server sends conversation_id for new conversations
        if (msg.type === 'conversation_started' && msg.conversation_id) {
          const cid = msg.conversation_id as string
          setActiveId(cid)
          setSearchParams({ c: cid })
          refreshConversations()
        }
        if (msg.type === 'title_updated' && msg.conversation_id && msg.title) {
          setConversationTitle(msg.title as string)
          refreshConversations()
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
  }, [setActiveId, setSearchParams, refreshConversations])

  // Load conversation messages when switching
  useEffect(() => {
    const cid = searchParams.get('c') || activeConversationId
    if (!cid) {
      // New conversation
      if (loadedConvRef.current !== null) {
        setMessages([])
        setConversationTitle(null)
        loadedConvRef.current = null
      }
      return
    }
    if (cid === loadedConvRef.current) return
    loadedConvRef.current = cid

    // Load conversation details + messages
    Promise.all([
      get<{ id: string; title?: string }>(`/api/conversations/${cid}`).catch(() => null),
      get<{ messages: { role: string; content: string; timestamp: string }[] }>(
        `/api/conversations/${cid}/messages`
      ).catch(() => null),
    ]).then(([conv, data]) => {
      if (conv) setConversationTitle(conv.title || null)
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
  }, [activeConversationId, searchParams])

  // File handling
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
  }, [inputValue, pendingFiles, activeConversationId])

  function formatFileSize(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  const headerTitle = conversationTitle || (messages.length > 0 ? 'Conversation' : 'New conversation')

  return (
    <FileUpload onFilesAdded={handleFilesAdded}>
      <div className="flex-1 flex flex-col">
        {/* Header */}
        <div className="px-6 py-4">
          <h2 className="text-sm font-medium text-muted-foreground">{headerTitle}</h2>
        </div>

        {/* Drag overlay */}
        <FileUploadContent>
          <div className="rounded-xl border-2 border-dashed border-primary/50 bg-primary/5 p-12 text-center">
            <p className="text-lg font-medium text-primary">Drop files here</p>
            <p className="text-sm text-muted-foreground mt-1">Files will be uploaded and attached to your message</p>
          </div>
        </FileUploadContent>

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
                      <>
                        {msg.content}
                        {msg.attachments && msg.attachments.length > 0 && (
                          <div className="mt-2 space-y-1">
                            {msg.attachments.map((a) => (
                              <div key={a.id} className="text-xs opacity-75 flex items-center gap-1">
                                <Paperclip className="h-3 w-3" />
                                {a.filename} ({formatFileSize(a.size)})
                              </div>
                            ))}
                          </div>
                        )}
                      </>
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

        {/* Pending files */}
        {pendingFiles.length > 0 && (
          <div className="px-6">
            <div className="max-w-3xl mx-auto flex flex-wrap gap-2 pb-2">
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
          </div>
        )}

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
              <PromptInputActions className="justify-between px-2 pb-2">
                <div className="flex items-center gap-1">
                  <FileUploadTrigger asChild>
                    <PromptInputAction tooltip="Attach files">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 rounded-full"
                        disabled={!connected}
                      >
                        <Paperclip className="h-4 w-4" />
                      </Button>
                    </PromptInputAction>
                  </FileUploadTrigger>
                </div>
                <PromptInputAction tooltip="Send message">
                  <Button
                    variant="default"
                    size="icon"
                    className="h-8 w-8 rounded-full"
                    disabled={!connected || (!inputValue.trim() && pendingFiles.length === 0)}
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
    </FileUpload>
  )
}
