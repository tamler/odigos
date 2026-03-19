import { useEffect, useRef, useState, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ChatSocket } from '@/lib/ws'
import { get, uploadFile } from '@/lib/api'
import { toast } from 'sonner'
import { ArrowUp, Paperclip, X, Mic, MicOff, Volume2, PanelRightClose } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Markdown } from '@/components/ui/markdown'
import { Loader } from '@/components/ui/loader'
import {
  ChatContainerRoot,
  ChatContainerContent,
  ChatContainerScrollAnchor,
} from '@/components/ui/chat-container'
import { FileUpload, FileUploadTrigger, FileUploadContent } from '@/components/ui/file-upload'
import { Artifact, ArtifactCard, getFileIcon } from '@/components/ArtifactCard'

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  timestamp: string
  attachments?: { id: string; filename: string; size: number }[]
}

interface ChatPanelProps {
  activeConversationId: string | null
  setActiveId: (id: string | null) => void
  refreshConversations: () => void
  socketRef: React.MutableRefObject<ChatSocket | null>
  connected: boolean
  chatContext?: Record<string, string>
  isSidePanel?: boolean
  onClose?: () => void
}

export function ChatPanel({
  activeConversationId,
  setActiveId,
  refreshConversations,
  socketRef,
  connected,
  chatContext,
  isSidePanel = false,
  onClose,
}: ChatPanelProps) {
  const [searchParams, setSearchParams] = useSearchParams()
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [artifacts, setArtifacts] = useState<Artifact[]>([])
  const [streamingContent, setStreamingContent] = useState('')
  const [thinking, setThinking] = useState(false)
  const [status, setStatus] = useState<string | null>(null)
  const [inputValue, setInputValue] = useState('')
  const [pendingFiles, setPendingFiles] = useState<{ file: File; id?: string; uploading?: boolean; progress?: number }[]>([])
  const [recording, setRecording] = useState(false)
  const [voiceEnabled, setVoiceEnabled] = useState(false)
  const [queuedCount, setQueuedCount] = useState(0)
  const loadedConvRef = useRef<string | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const audioWsRef = useRef<WebSocket | null>(null)

  // Wire up message handler on the shared socket
  useEffect(() => {
    const socket = socketRef.current
    if (!socket) return

    socket.onMessage = (msg) => {
      if (msg.type === 'status') {
        setStatus(msg.text as string)
      }
      if (msg.type === 'chat_chunk') {
        if (msg.conversation_id && loadedConvRef.current && msg.conversation_id !== loadedConvRef.current) {
          return // Ignore chunks for inactive conversations
        }
        setThinking(false)
        setStatus(null)
        setStreamingContent((prev) => prev + (msg.content as string))
      }
      if (msg.type === 'chat_response') {
        if (msg.conversation_id && loadedConvRef.current && msg.conversation_id !== loadedConvRef.current) {
          return // Ignore responses for inactive conversations
        }
        setThinking(false)
        setStatus(null)
        setStreamingContent('')
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
      if (msg.type === 'queue_update') {
        const queued = msg.queued as number
        setQueuedCount(queued)
        if (queued === 0) {
          setThinking(false)
        }
      }
      if (msg.type === 'message_queued') {
        setStatus(`Queued (${msg.queued as number} pending)`)
      }
      if (msg.type === 'queue_full') {
        toast.warning('Message queue is full. Please wait.')
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

    setThinking(false)
    setStatus(null)

    Promise.allSettled([
      get<{ messages: { role: string; content: string; timestamp: string }[] }>(`/api/conversations/${cid}/messages`),
      get<{ artifacts: Artifact[] }>(`/api/artifacts?conversation_id=${cid}`)
    ]).then(([msgRes, artRes]) => {
      if (msgRes.status === 'fulfilled' && msgRes.value?.messages) {
        setMessages(
          msgRes.value.messages.map((m) => ({
            role: m.role as 'user' | 'assistant',
            content: m.content,
            timestamp: m.timestamp,
          }))
        )
      }
      if (artRes.status === 'fulfilled' && artRes.value?.artifacts) {
        setArtifacts(artRes.value.artifacts)
      }
    }).catch(() => {})
  }, [activeConversationId, searchParams])

  // Fetch artifacts when thinking completes
  useEffect(() => {
    if (!thinking && loadedConvRef.current) {
      get<{ artifacts: Artifact[] }>(`/api/artifacts?conversation_id=${loadedConvRef.current}`)
        .then(res => {
          if (res?.artifacts) setArtifacts(res.artifacts)
        })
        .catch(() => {})
    }
  }, [thinking])

  // Auto-resize textarea
  useEffect(() => {
    const ta = textareaRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = Math.min(ta.scrollHeight, 200) + 'px'
  }, [inputValue])

  // Timeout fallback for thinking state
  useEffect(() => {
    if (!thinking) return
    const timer = setTimeout(() => {
      setThinking(false)
      setStatus(null)
    }, 60000)
    return () => clearTimeout(timer)
  }, [thinking, status])

  // Check voice settings
  useEffect(() => {
    get<Record<string, any>>('/api/settings')
      .then((s) => setVoiceEnabled(!!(s.stt?.enabled || s.tts?.enabled)))
      .catch(() => {})
  }, [])

  const startRecording = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const recorder = new MediaRecorder(stream)
      mediaRecorderRef.current = recorder

      const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
      const ws = new WebSocket(`${protocol}://${window.location.host}/ws/audio/input`)
      audioWsRef.current = ws

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          if (data.text) {
            setInputValue((prev: string) => prev + (prev ? ' ' : '') + data.text)
          }
        } catch {
          // ignore non-JSON frames
        }
      }

      ws.onopen = () => {
        recorder.ondataavailable = (e) => {
          if (e.data.size > 0 && ws.readyState === WebSocket.OPEN) {
            ws.send(e.data)
          }
        }
        recorder.start(500)
        setRecording(true)
      }

      ws.onerror = () => {
        toast.error('Audio WebSocket error')
        stopRecording()
      }
    } catch {
      toast.error('Microphone access denied')
    }
  }, [])

  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop()
      mediaRecorderRef.current.stream.getTracks().forEach((t) => t.stop())
    }
    mediaRecorderRef.current = null

    if (audioWsRef.current) {
      audioWsRef.current.close()
      audioWsRef.current = null
    }
    setRecording(false)
  }, [])

  const playTTS = useCallback(async (text: string) => {
    try {
      const res = await fetch(`/api/audio/speak?text=${encodeURIComponent(text)}`)
      if (!res.ok) {
        toast.error('TTS request failed')
        return
      }
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const audio = new Audio(url)
      audio.onended = () => URL.revokeObjectURL(url)
      audio.play()
    } catch {
      toast.error('TTS playback failed')
    }
  }, [])

  const handleFilesAdded = useCallback(async (files: File[]) => {
    const newEntries = files.map((file) => ({ file, uploading: true, progress: 0 }))
    setPendingFiles((prev) => [...prev, ...newEntries])

    for (let i = 0; i < files.length; i++) {
      try {
        const result = await uploadFile(files[i], (progress) => {
          setPendingFiles((prev) =>
            prev.map((p) => p.file === files[i] ? { ...p, progress } : p)
          )
        })
        setPendingFiles((prev) =>
          prev.map((p) =>
            p.file === files[i] ? { ...p, id: result.id, uploading: false, progress: 100 } : p
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
      context: chatContext,
    })

    setInputValue('')
    setPendingFiles([])
  }, [inputValue, pendingFiles, activeConversationId, socketRef, chatContext])

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

  const canSend = connected && (inputValue.trim() || pendingFiles.length > 0) && queuedCount < 3

  return (
    <FileUpload onFilesAdded={handleFilesAdded}>
      <div className="flex-1 flex flex-col h-full bg-background z-10 w-full overflow-hidden">
        {/* Header for Side Panel Mode */}
        {isSidePanel && (
          <div className="flex items-center justify-between px-4 h-[52px] border-b border-border/40 shrink-0 lg:pt-0 pt-2 lg:mt-0 lg:bg-transparent bg-background/50 backdrop-blur-sm shadow-sm sticky top-0 z-20">
            <div>
              <div className="text-sm font-medium">Copilot</div>
              {chatContext && Object.keys(chatContext).length > 0 && (
                <div className="text-xs text-muted-foreground mt-0.5">Context active</div>
              )}
            </div>
            {onClose && (
              <Button variant="ghost" size="icon" aria-label="Close chat panel" onClick={onClose} className="shrink-0 h-8 w-8 hover:bg-muted">
                <PanelRightClose className="h-4 w-4" />
              </Button>
            )}
          </div>
        )}

        {/* Drag overlay */}
        <FileUploadContent>
          <div className="rounded-xl border-2 border-dashed border-primary/50 bg-primary/5 p-12 text-center">
            <p className="text-lg font-medium text-primary">Drop files here</p>
            <p className="text-sm text-muted-foreground mt-1">Files will be uploaded and attached to your message</p>
          </div>
        </FileUploadContent>

        {/* Messages area */}
        <ChatContainerRoot className="flex-1 w-full relative z-0">
          <ChatContainerContent>
            <div className={`w-full mx-auto px-4 py-6 space-y-6 ${!isSidePanel ? 'max-w-[52rem]' : ''}`}>
              {messages.length === 0 && !thinking && (
                <div className="flex items-center justify-center h-[60vh] text-muted-foreground text-base text-center">
                  What can I help you with?
                </div>
              )}
              {messages.map((msg, i) => (
                <div key={i}>
                  {msg.role === 'user' ? (
                    <div className="flex justify-end">
                      <div className="max-w-[85%]">
                        <div className="rounded-3xl bg-muted/60 px-5 py-3">
                          <div className="text-sm text-foreground whitespace-pre-wrap leading-relaxed break-words overflow-hidden">{msg.content}</div>
                        </div>
                        {msg.attachments && msg.attachments.length > 0 && (
                          <div className="mt-1.5 flex justify-end gap-2 flex-wrap">
                            {msg.attachments.map((a) => (
                              <div key={a.id} className="text-xs text-muted-foreground flex items-center gap-1">
                                <Paperclip className="h-3 w-3 shrink-0" />
                                <span className="truncate">{a.filename}</span> ({formatFileSize(a.size)})
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  ) : (
                    <div className="group/msg w-full overflow-hidden">
                      <div className="text-sm text-foreground leading-relaxed break-words prose dark:prose-invert max-w-none">
                        <Markdown>{msg.content}</Markdown>
                      </div>
                      {voiceEnabled && (
                        <button
                          onClick={() => playTTS(msg.content)}
                          className="mt-1 opacity-0 group-hover/msg:opacity-100 transition-opacity text-muted-foreground hover:text-foreground"
                          title="Read aloud"
                          aria-label="Read aloud"
                        >
                          <Volume2 className="h-4 w-4" />
                        </button>
                      )}
                    </div>
                  )}
                </div>
              ))}
              {streamingContent && (
                <div className="group/msg w-full overflow-hidden">
                  <div className="text-sm text-foreground leading-relaxed break-words prose dark:prose-invert max-w-none">
                    <Markdown>{streamingContent}</Markdown>
                  </div>
                </div>
              )}
              {thinking && (
                <div className="flex items-center gap-2">
                  <Loader variant="typing" />
                  <span className="text-xs text-muted-foreground animate-pulse">
                    {status || 'Thinking...'}
                  </span>
                </div>
              )}
              {artifacts.length > 0 && (
                <div className="pt-4 mt-6 border-t border-border/40">
                  <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">Generated Artifacts</h3>
                  <div className="flex flex-wrap gap-3">
                    {artifacts.map(a => (
                      <ArtifactCard key={a.id} artifact={a} />
                    ))}
                  </div>
                </div>
              )}
            </div>
            <ChatContainerScrollAnchor />
          </ChatContainerContent>
        </ChatContainerRoot>

        {/* Input area */}
        <div className="pb-6 sm:pb-4 pt-2 px-4 shrink-0 bg-background/50 backdrop-blur-sm">
          <div className={`w-full mx-auto ${!isSidePanel ? 'max-w-[52rem]' : ''}`}>
            {/* Pending files */}
            {pendingFiles.length > 0 && (
              <div className="flex flex-wrap gap-2 pb-3">
                {pendingFiles.map((p, i) => (
                  <div
                    key={i}
                    className="flex items-center gap-2.5 px-3 py-2 rounded-lg bg-muted border border-border/50 text-sm max-w-[240px] shadow-sm relative overflow-hidden group"
                  >
                    <div className="text-muted-foreground shrink-0 flex items-center justify-center p-1 bg-background rounded-md">
                      {getFileIcon(p.file.type || 'application/octet-stream', p.file.name)}
                    </div>
                    <div className="flex flex-col min-w-0 flex-1 py-0.5">
                      <span className="truncate text-xs font-semibold">{p.file.name}</span>
                      <div className="flex items-center gap-2 mt-0.5">
                        <span className="text-[10px] text-muted-foreground">{formatFileSize(p.file.size)}</span>
                        {p.uploading && (
                          <div className="flex items-center gap-1.5 ml-auto">
                            <div className="h-1 flex-1 bg-background rounded-full overflow-hidden w-10">
                              <div className="h-full bg-primary transition-all duration-300" style={{ width: `${p.progress || 0}%` }} />
                            </div>
                            <span className="text-[9px] text-muted-foreground font-medium w-5 text-right">{p.progress || 0}%</span>
                          </div>
                        )}
                      </div>
                    </div>
                    {!p.uploading && (
                      <button onClick={() => removeFile(p.file)} aria-label="Remove file" className="shrink-0 text-muted-foreground hover:text-foreground p-1 rounded-sm hover:bg-background transition-colors absolute right-1.5 top-1.5 opacity-0 group-hover:opacity-100">
                        <X className="h-3 w-3" />
                      </button>
                    )}
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
                    aria-label="Attach file"
                    className="h-8 w-8 rounded-lg text-muted-foreground hover:text-foreground"
                    disabled={!connected}
                  >
                    <Paperclip className="h-4 w-4" />
                  </Button>
                </FileUploadTrigger>
                <div className="flex items-center gap-1">
                  {voiceEnabled && (
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={recording ? "Stop dictation" : "Start dictation"}
                      className={`h-8 w-8 rounded-lg text-muted-foreground hover:text-foreground ${recording ? 'text-red-500 animate-pulse' : ''}`}
                      disabled={!connected}
                      onClick={recording ? stopRecording : startRecording}
                    >
                      {recording ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
                    </Button>
                  )}
                  <Button
                    size="icon"
                    aria-label="Send message"
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
      </div>
    </FileUpload>
  )
}
