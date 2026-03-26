import { useEffect, useRef, useState, useCallback } from 'react'
import { useSearchParams, useNavigate, useOutletContext } from 'react-router-dom'
import { ChatSocket } from '@/lib/ws'
import { get, uploadFile } from '@/lib/api'
import { toast } from 'sonner'
import { ArrowUp, Paperclip, X, Mic, MicOff, PanelRightClose, Square, Camera } from 'lucide-react'
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
import { MessageActions } from '@/components/MessageActions'
import { VoiceOrb, VoiceState } from '@/components/VoiceOrb'

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

function WelcomeView({ agentName, onSuggest }: { agentName: string; onSuggest: (text: string) => void }) {
  const suggestions = [
    { text: "What can you do?", label: "Capabilities" },
    { text: "Start a journal entry", label: "Journal" },
    { text: "Create a task board for my project", label: "Task Board" },
    { text: "Research the latest trends in AI agents", label: "Research" },
  ]

  return (
    <div className="flex-1 flex flex-col items-center justify-center p-6 text-center animate-in fade-in zoom-in duration-500">
      <div className="max-w-md space-y-6">
        <div className="space-y-2">
          <div className="h-12 w-12 bg-primary/10 rounded-2xl flex items-center justify-center mx-auto mb-4">
            <span className="text-2xl font-bold text-primary">{agentName[0]}</span>
          </div>
          <h1 className="text-2xl font-bold tracking-tight">Hello, I'm {agentName}</h1>
          <p className="text-muted-foreground">Your personal AI assistant that learns and improves over time. How can I help you today?</p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {suggestions.map((s) => (
            <button
              key={s.label}
              onClick={() => onSuggest(s.text)}
              className="p-4 rounded-xl border border-border/40 bg-card hover:border-primary/50 hover:bg-primary/5 transition-all text-left group"
            >
              <p className="text-xs font-semibold text-primary mb-1 uppercase tracking-wider">{s.label}</p>
              <p className="text-sm text-muted-foreground group-hover:text-foreground transition-colors">{s.text}</p>
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

export function ChatPanel({
  activeConversationId,
  socketRef,
  connected,
  chatContext,
  isSidePanel = false,
  onClose,
}: ChatPanelProps) {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const { 
    hasNewEmail, 
    setHasNewEmail, 
    artifactPanelOpen, 
    setArtifactPanelOpen, 
    setActiveArtifactId,
    isMobile,
    messages,
    setMessages,
    streamingContent,
    thinking,
    setThinking,
    status,
    setStatus,
    queuedCount,
    suggestedActions,
    setSuggestedActions,
  } = useOutletContext<any>()
  const [messageDisplayLimit, setMessageDisplayLimit] = useState(100)
  const [artifacts, setArtifacts] = useState<Artifact[]>([])
  const [inputValue, setInputValue] = useState('')
  const [pendingFiles, setPendingFiles] = useState<{ file: File; id?: string; uploading?: boolean; progress?: number }[]>([])
  const [recording, setRecording] = useState(false)
  const [sttAvailable, setSttAvailable] = useState(false)
  const [ttsAvailable, setTtsAvailable] = useState(false)
  const [isStreaming, setIsStreaming] = useState(false)
  const [agentName, setAgentName] = useState('Odigos')
  const [showAllActions, setShowAllActions] = useState(false)
  const [useCamera, setUseCamera] = useState<boolean | 'environment'>(false)
  const [voiceMode, setVoiceMode] = useState(false)
  const [voiceOrbState, setVoiceOrbState] = useState<VoiceState>('idle')
  const [amplitude] = useState(0)
  const loadedConvRef = useRef<string | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const currentAudioRef = useRef<HTMLAudioElement | null>(null)

  // Wire up message handler on the shared socket
  useEffect(() => {
    // socket.onMessage is now handled globally in AppLayout.tsx
    // to keep messages in sync across chat and floating bubble.
  }, [])

  // Sync voice orb state with agent status (G-B6)
  useEffect(() => {
    if (!voiceMode) return
    if (thinking) setVoiceOrbState('thinking')
    else if (isStreaming) setVoiceOrbState('speaking')
    else if (recording) setVoiceOrbState('listening')
    else setVoiceOrbState('idle')
  }, [voiceMode, thinking, isStreaming, recording])

  // Auto-open new artifacts (G38)
  const prevArtifactsCount = useRef(0)
  useEffect(() => {
    if (artifacts.length > prevArtifactsCount.current) {
      const latest = artifacts[0] // list is sorted by created_at DESC
      if (latest && !artifactPanelOpen) {
        setActiveArtifactId(latest.id)
        setArtifactPanelOpen(true)
      }
    }
    prevArtifactsCount.current = artifacts.length
  }, [artifacts, artifactPanelOpen, setActiveArtifactId, setArtifactPanelOpen])

  // Load conversation messages when switching
  useEffect(() => {
    get<any>('/api/settings').then(s => setAgentName(s.agent.name)).catch(() => {})

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

  // Check voice and agent settings (G-V5, G-V6)
  useEffect(() => {
    get<Record<string, any>>('/api/settings')
      .then((s) => {
        setSttAvailable(s.voice?.stt_provider !== 'disabled')
        setTtsAvailable(s.voice?.tts_provider !== 'disabled')
      })
      .catch(() => {})
  }, [])

  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const audioStreamRef = useRef<MediaStream | null>(null)

  const startRecording = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      })
      audioStreamRef.current = stream

      const recorder = new MediaRecorder(stream)
      mediaRecorderRef.current = recorder
      const chunks: Blob[] = []

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunks.push(e.data)
      }

      recorder.onstop = async () => {
        const blob = new Blob(chunks, { type: recorder.mimeType })
        if (blob.size < 1000) return // too short, skip

        // POST the audio file to the transcribe endpoint
        try {
          const formData = new FormData()
          const ext = recorder.mimeType.includes('mp4') ? 'mp4'
            : recorder.mimeType.includes('ogg') ? 'ogg' : 'webm'
          formData.append('audio', blob, `recording.${ext}`)

          const res = await fetch('/api/audio/transcribe', {
            method: 'POST',
            credentials: 'include',
            body: formData,
          })
          if (res.ok) {
            const data = await res.json()
            if (data.text) {
              setInputValue((prev: string) => prev + (prev ? ' ' : '') + data.text)
            }
          }
        } catch (err) {
          console.error('Transcription request failed:', err)
        }
      }

      recorder.start()
      setRecording(true)
    } catch {
      toast.error('Microphone access denied')
    }
  }, [])

  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop()
    }
    mediaRecorderRef.current = null
    if (audioStreamRef.current) {
      audioStreamRef.current.getTracks().forEach(t => t.stop())
      audioStreamRef.current = null
    }
    setRecording(false)
  }, [])

  const [isTTSPlaying, setIsTTSPlaying] = useState(false)

  const playTTS = useCallback(async (text: string) => {
    if (currentAudioRef.current) {
      currentAudioRef.current.pause()
      currentAudioRef.current.src = ''
      currentAudioRef.current = null
      setIsTTSPlaying(false)
    }
    if (!text) return
    try {
      const res = await fetch(`/api/audio/speak?text=${encodeURIComponent(text)}`, {
        credentials: 'include',
      })
      if (!res.ok) return
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const audio = new Audio(url)
      currentAudioRef.current = audio
      setIsTTSPlaying(true)
      audio.onended = () => {
        URL.revokeObjectURL(url)
        currentAudioRef.current = null
        setIsTTSPlaying(false)
      }
      audio.play()
    } catch {
      setIsTTSPlaying(false)
    }
  }, [])

  const stopTTS = useCallback(() => {
    if (currentAudioRef.current) {
      currentAudioRef.current.pause()
      currentAudioRef.current.src = ''
      currentAudioRef.current = null
    }
    setIsTTSPlaying(false)
  }, [])

  const handleEdit = useCallback((messageIndex: number, content: string) => {
    socketRef.current?.send('edit', {
      message_index: messageIndex,
      content,
      conversation_id: activeConversationId,
    })
    // Truncate local messages state to match
    setMessages((prev: ChatMessage[]) => prev.slice(0, messageIndex))
  }, [activeConversationId, socketRef])


  const getPreviousUserMessage = (assistantIndex: number): string => {
    for (let i = assistantIndex - 1; i >= 0; i--) {
      if (messages[i]?.role === 'user') return messages[i].content
    }
    return ''
  }

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

  function handleSend(overrideContent?: string) {
    const content = (overrideContent ?? inputValue).trim()
    if (!content && pendingFiles.length === 0) return

    const attachments = pendingFiles
      .filter((p) => p.id)
      .map((p) => ({ id: p.id!, filename: p.file.name, size: p.file.size }))

    setMessages((prev: ChatMessage[]) => [...prev, {
      role: 'user',
      content,
      timestamp: new Date().toISOString(),
      attachments: attachments.length > 0 ? attachments : undefined,
    }])
    setThinking(true)
    setIsStreaming(true)
    setSuggestedActions([])

    socketRef.current?.send('chat', {
      content,
      conversation_id: activeConversationId || undefined,
      attachments: attachments.length > 0 ? attachments : undefined,
      context: chatContext,
    })

    setInputValue('')
    setPendingFiles([])
  }

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
    <FileUpload onFilesAdded={handleFilesAdded} capture={useCamera || undefined}>
      <div className="flex-1 flex flex-col h-full bg-background relative overflow-hidden">
        {/* Header — only show close button for side panel */}
        {onClose && (
          <div className="flex items-center justify-end px-4 h-[40px] shrink-0">
            <Button variant="ghost" size="icon" aria-label="Close chat panel" onClick={onClose} className="shrink-0 h-8 w-8 hover:bg-muted">
              <PanelRightClose className="h-4 w-4" />
            </Button>
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
            <div className={`w-full h-full mx-auto px-4 py-6 ${!isSidePanel ? 'max-w-[52rem]' : ''}`}>
              {messages.length === 0 && !activeConversationId ? (
                <WelcomeView 
                  agentName={agentName} 
                  onSuggest={(text) => handleSend(text)} 
                />
              ) : (
                <div className="flex-1 flex flex-col h-full min-h-0">
                  {voiceMode ? (
                    <div className="flex-1 flex flex-col h-full">
                      {/* Compact transcript above orb */}
                      <div className="flex-1 overflow-y-auto px-4 py-6 space-y-4 opacity-40 hover:opacity-100 transition-opacity">
                         {messages.slice(-5).map((msg: ChatMessage, i: number) => (
                           <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                             <div className={`max-w-[80%] rounded-2xl px-4 py-2 text-xs ${msg.role === 'user' ? 'bg-primary/20' : 'bg-muted/40'}`}>
                               {msg.content}
                             </div>
                           </div>
                         ))}
                      </div>
                      <VoiceOrb 
                        state={voiceOrbState} 
                        amplitude={amplitude}
                        onExit={() => setVoiceMode(false)}
                        onToggleMic={() => recording ? stopRecording() : startRecording()}
                      />
                    </div>
                  ) : (
                    <div className="space-y-6">
                      {messages.length === 0 && !thinking && (
                        <div className="flex items-center justify-center h-[60vh] text-muted-foreground text-base text-center">
                          What can I help you with?
                        </div>
                      )}
                      
                      {messages.length > messageDisplayLimit && (
                        <div className="flex justify-center pb-2">
                          <Button variant="outline" size="sm" onClick={() => setMessageDisplayLimit(l => l + 100)} className="text-xs h-7">
                            Load earlier messages
                          </Button>
                        </div>
                      )}

                      {(() => {
                        const offset = Math.max(0, messages.length - messageDisplayLimit)
                        return messages.slice(-messageDisplayLimit).map((msg: ChatMessage, i: number) => {
                          const actualIndex = offset + i
                          return (
                            <div key={i}>
                              {msg.role === 'user' ? (
                                <div className="group/msg flex flex-col items-end">
                                  <div className="max-w-[90%] sm:max-w-[85%]">
                                    <div className="rounded-2xl sm:rounded-3xl bg-muted/60 px-3 py-2 sm:px-5 sm:py-3 shadow-sm border border-border/20">
                                      <div className="text-sm text-foreground whitespace-pre-wrap leading-relaxed break-words overflow-hidden">{msg.content}</div>
                                    </div>
                                    <MessageActions
                                      role="user"
                                      content={msg.content}
                                      messageIndex={actualIndex}
                                      conversationId={activeConversationId || ''}
                                      isStreaming={isStreaming}
                                      ttsAvailable={ttsAvailable}
                                      socket={socketRef.current}
                                      onEdit={handleEdit}
                                      playTTS={playTTS}
                                      stopTTS={stopTTS}
                                      isTTSPlaying={isTTSPlaying}
                                    />
                                  </div>
                                </div>
                              ) : (
                                <div className="group/msg w-full overflow-hidden mb-4">
                                  <div className="chat-text text-foreground break-words prose dark:prose-invert max-w-none prose-p:my-3 prose-li:my-1 prose-headings:mt-5 prose-headings:mb-2">
                                    <Markdown>{msg.content}</Markdown>
                                  </div>
                                  <MessageActions
                                    role="assistant"
                                    content={msg.content}
                                    messageIndex={actualIndex}
                                    conversationId={activeConversationId || ''}
                                    previousUserMessage={getPreviousUserMessage(actualIndex)}
                                    isStreaming={isStreaming}
                                    ttsAvailable={ttsAvailable}
                                    socket={socketRef.current}
                                    onEdit={() => {}}
                                    playTTS={playTTS}
                                      stopTTS={stopTTS}
                                      isTTSPlaying={isTTSPlaying}
                                  />
                                </div>
                              )}
                            </div>
                          )
                        })
                      })()}

                      {streamingContent && (
                        <div className="group/msg w-full overflow-hidden">
                          <div className="chat-text text-foreground break-words prose dark:prose-invert max-w-none prose-p:my-3 prose-li:my-1 prose-headings:mt-5 prose-headings:mb-2">
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
                        <div className="pt-4 mt-6">
                          <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">Generated Artifacts</h3>
                          <div className="flex flex-wrap gap-3">
                            {artifacts.map(a => (
                              <ArtifactCard key={a.id} artifact={a} />
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
            <ChatContainerScrollAnchor />
          </ChatContainerContent>
        </ChatContainerRoot>

        {/* Suggested action buttons */}
        {suggestedActions.length > 0 && (
          <div className="px-4 pt-2">
            <div className={`w-full mx-auto flex flex-wrap gap-2 ${!isSidePanel ? 'max-w-[52rem]' : ''}`}>
              {(showAllActions ? suggestedActions : suggestedActions.slice(0, 5)).map((action: string, i: number) => (
                <button
                  key={i}
                  onClick={() => {
                    setSuggestedActions([])
                    setMessages((prev: ChatMessage[]) => [...prev, { role: 'user', content: action, timestamp: new Date().toISOString() }])
                    setThinking(true)
                    socketRef.current?.send('chat', { content: action, conversation_id: activeConversationId || undefined })
                  }}
                  className="inline-flex items-center gap-1.5 px-3 py-2 rounded-full text-[13px] bg-muted/50 text-muted-foreground hover:bg-primary/10 hover:text-primary transition-all border border-border/40 hover:border-primary/20 shadow-sm"
                >
                  {action.length > 60 ? action.slice(0, 57) + '...' : action}
                </button>
              ))}
              
              {suggestedActions.length > 5 && (
                <button
                  onClick={() => setShowAllActions(!showAllActions)}
                  className="inline-flex items-center gap-1.5 px-3 py-2 rounded-full text-[13px] text-muted-foreground hover:text-foreground transition-colors font-medium"
                >
                  {showAllActions ? 'Show less' : `+${suggestedActions.length - 5} more`}
                </button>
              )}

              <button
                onClick={() => {
                  setSuggestedActions([])
                  const allMsg = `Do all of these: ${suggestedActions.join(', ')}`
                  setMessages((prev: ChatMessage[]) => [...prev, { role: 'user', content: allMsg, timestamp: new Date().toISOString() }])
                  setThinking(true)
                  socketRef.current?.send('chat', { content: allMsg, conversation_id: activeConversationId || undefined })
                }}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-full text-[13px] bg-primary text-primary-foreground hover:bg-primary/90 transition-all shadow-md font-semibold ml-auto"
              >
                Do all
              </button>
            </div>
          </div>
        )}

        {/* Input area */}
        <div className="pb-safe pt-2 px-4 shrink-0 bg-background/50 backdrop-blur-sm">
          <div className={`w-full mx-auto ${!isSidePanel ? 'max-w-[52rem]' : ''} pb-4 sm:pb-4`}>
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
            <div className="relative rounded-2xl border border-border/50 bg-muted/30 focus-within:border-border/80 transition-colors shadow-sm">
              <textarea
                ref={textareaRef}
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Send a message..."
                disabled={!connected}
                rows={1}
                className="w-full resize-none bg-transparent px-4 pt-3 pb-14 sm:pb-12 text-base sm:text-sm text-foreground placeholder:text-muted-foreground focus:outline-none disabled:opacity-50 min-h-[52px]"
              />
              <div className="absolute bottom-2 left-2 right-2 flex items-center justify-between">
                <div className="flex items-center gap-1">
                  <FileUploadTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label="Attach file"
                      className="h-11 w-11 lg:h-8 lg:w-8 rounded-lg text-muted-foreground hover:text-foreground"
                      disabled={!connected}
                      onClick={() => setUseCamera(false)}
                    >
                      <Paperclip className="h-5 w-5 lg:h-4 lg:w-4" />
                    </Button>
                  </FileUploadTrigger>
                  
                  {isMobile && (
                    <FileUploadTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label="Take photo"
                        className="h-11 w-11 rounded-lg text-muted-foreground hover:text-foreground"
                        disabled={!connected}
                        onClick={() => setUseCamera('environment')}
                      >
                        <Camera className="h-5 w-5" />
                      </Button>
                    </FileUploadTrigger>
                  )}
                </div>

                <div className="flex items-center gap-1">
                  {sttAvailable && (
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={recording ? "Stop dictation" : "Start dictation"}
                      className={`h-11 w-11 lg:h-8 lg:w-8 rounded-lg text-muted-foreground hover:text-foreground ${recording ? 'text-red-500 animate-pulse' : ''}`}
                      disabled={!connected}
                      onClick={recording ? stopRecording : startRecording}
                    >
                      {recording ? <MicOff className="h-5 w-5 lg:h-4 lg:w-4" /> : <Mic className="h-5 w-5 lg:h-4 lg:w-4" />}
                    </Button>
                  )}
                  {isStreaming ? (
                    <Button
                      size="icon"
                      aria-label="Stop generation"
                      className="h-11 w-11 lg:h-8 lg:w-8 rounded-lg bg-red-500 hover:bg-red-600 text-white shadow-sm transition-all active:scale-95 flex items-center justify-center"
                      onClick={() => {
                        socketRef.current?.send('cancel')
                        setIsStreaming(false)
                        if (currentAudioRef.current) {
                          currentAudioRef.current.pause()
                          currentAudioRef.current = null
                        }
                      }}
                    >
                      <Square className="h-5 w-5 lg:h-4 lg:w-4 fill-current" />
                    </Button>
                  ) : (
                    <Button
                      size="icon"
                      aria-label="Send message"
                      className="h-11 w-11 lg:h-8 lg:w-8 rounded-lg shadow-sm transition-all active:scale-95 flex items-center justify-center"
                      disabled={!canSend}
                      onClick={() => handleSend()}
                    >
                      <ArrowUp className="h-5 w-5 lg:h-4 lg:w-4" />
                    </Button>
                  )}
                </div>
              </div>
            </div>

            {/* Quick Links */}
            {!isSidePanel && (
              <div className="flex justify-center gap-4 mt-3 text-xs text-muted-foreground/70 sm:text-[11px] font-medium tracking-wide">
                <button onClick={() => navigate('/notebooks')} className="hover:text-foreground transition-colors">Journal</button>
                <span>&middot;</span>
                <button onClick={() => navigate('/kanban')} className="hover:text-foreground transition-colors">Board</button>
                <span>&middot;</span>
                <button onClick={() => navigate('/settings?tab=documents')} className="hover:text-foreground transition-colors">Documents</button>
                <span>&middot;</span>
                {sttAvailable && (
                  <>
                    <button onClick={() => setVoiceMode(true)} className="hover:text-foreground transition-colors">Voice</button>
                    <span>&middot;</span>
                  </>
                )}
                <button 
                  onClick={() => {
                    setHasNewEmail(false)
                    handleSend('Check my email')
                  }} 
                  className="hover:text-foreground transition-colors relative"
                >
                  Email
                  {hasNewEmail && (
                    <span className="absolute -top-1 -right-2 h-2 w-2 bg-red-500 rounded-full border border-background shadow-sm animate-pulse" />
                  )}
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </FileUpload>
  )
}
