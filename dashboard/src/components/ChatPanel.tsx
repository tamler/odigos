import { useEffect, useRef, useState, useCallback, memo } from 'react'
import { useSearchParams, useOutletContext, useNavigate } from 'react-router-dom'
import { ChatSocket } from '@/lib/ws'
import { get, uploadFile } from '@/lib/api'
import { toast } from 'sonner'
import { ArrowUp, Paperclip, X, Mic, PanelRightClose, Square, Camera } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Markdown } from '@/components/ui/markdown'
import {
  ChatContainerRoot,
  ChatContainerContent,
  ChatContainerScrollAnchor,
} from '@/components/ui/chat-container'
import { FileUpload, FileUploadTrigger, FileUploadContent } from '@/components/ui/file-upload'
import { Artifact, ArtifactCard, getFileIcon, formatFileSize } from '@/components/ArtifactCard'
import { MessageActions } from '@/components/MessageActions'
import { VoiceOrb } from '@/components/VoiceOrb'
import { useVoiceMode } from '@/hooks/useVoiceMode'
import { usePushToTalk } from '@/hooks/usePushToTalk'
import type { ChatMessage } from '@/layouts/AppLayout'

interface ChatPanelProps {
  activeConversationId: string | null
  socketRef: React.MutableRefObject<ChatSocket | null>
  connected: boolean
  chatContext?: Record<string, string>
  isSidePanel?: boolean
  onClose?: () => void
}

const ImageArtifact = ({ artifact, onClick }: { artifact: Artifact, onClick: () => void }) => {

  return (
    <div className="rounded-xl overflow-hidden border border-border/40 max-w-xs cursor-pointer hover:opacity-95 transition-all shadow-sm group/img"
         onClick={onClick}>
      <div className="relative aspect-square bg-muted flex items-center justify-center overflow-hidden">
        <img
          src={`/api/artifacts/${artifact.id}/thumbnail?size=400`}
          alt={artifact.filename}
          className="w-full h-full object-cover"
          loading="lazy"
        />
      </div>
    </div>
  )
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
            <span className="text-2xl font-bold text-primary">{(agentName || 'O')[0]}</span>
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

export const ChatPanel = memo(({
  activeConversationId,
  socketRef,
  connected,
  chatContext,
  isSidePanel = false,
  onClose,
}: ChatPanelProps) => {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  let outletCtx: any = {}
  try { outletCtx = useOutletContext<any>() || {} } catch { outletCtx = {} }
  const {
    artifactPanelOpen = false,
    setArtifactPanelOpen = () => {},
    setActiveArtifactId = () => {},
    isMobile = false,
    messages = [],
    setMessages = () => {},
    streamingContent = '',
    thinking = false,
    setThinking = () => {},
    status = null,
    setStatus = () => {},
    queuedCount = 0,
    suggestedActions = [],
    setSuggestedActions = () => {},
    playTTS: outletPlayTTS,
    stopTTS: outletStopTTS,
    isTTSPlaying: outletTTSPlaying,
    agentName: outletAgentName,
  } = outletCtx
  const [messageDisplayLimit, setMessageDisplayLimit] = useState(100)
  const [artifacts, setArtifacts] = useState<Artifact[]>([])
  const [inputValue, setInputValue] = useState(
    () => localStorage.getItem('odigos-draft') || ''
  )
  const [pendingFiles, setPendingFiles] = useState<{ file: File; id?: string; uploading?: boolean; progress?: number }[]>([])
  const [sttAvailable, setSttAvailable] = useState(false)
  const [ttsAvailable, setTtsAvailable] = useState(false)
  const [isStreaming, setIsStreaming] = useState(false)
  const agentName = outletAgentName || 'Odigos'
  const [showAllActions, setShowAllActions] = useState(false)
  const [useCamera, setUseCamera] = useState<boolean | 'environment'>(false)
  const [voiceAmplitude, setVoiceAmplitude] = useState(0)
  const loadedConvRef = useRef<string | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Voice mode: continuous listen → transcribe → send → TTS → repeat
  const voiceMode = useVoiceMode({
    onTranscription: (text) => {
      // Auto-send transcribed text as a chat message
      handleSendRef.current?.(text)
    },
    onPhaseChange: (phase) => {
      // Sync phase with streaming/thinking state
      if (phase === 'thinking' || phase === 'processing') {
        // Visual feedback handled by orb
      }
    },
    onAmplitudeChange: setVoiceAmplitude,
  })
  const handleSendRef = useRef<((text: string) => void) | null>(null)

  // Push-to-talk: hold mic → record → release → transcribe → insert into input
  const pushToTalk = usePushToTalk((text) => {
    setInputValue(prev => prev ? `${prev} ${text}` : text)
  })

  // Voice error feedback
  useEffect(() => {
    const handler = (e: Event) => {
      const msg = (e as CustomEvent).detail
      if (msg) toast.error(msg)
    }
    window.addEventListener('voice-error', handler)
    return () => window.removeEventListener('voice-error', handler)
  }, [])

  // Streaming starts when content arrives, ends when thinking stops
  useEffect(() => {
    if (streamingContent && !isStreaming) setIsStreaming(true)
    if (!thinking && isStreaming) setIsStreaming(false)
  }, [thinking, streamingContent, isStreaming])

  // Safety: clear thinking after 120s if server never responds
  useEffect(() => {
    if (!thinking) return
    const timer = setTimeout(() => {
      setThinking(false)
      setIsStreaming(false)
      setStatus(null)
    }, 120000)
    return () => clearTimeout(timer)
  }, [thinking])

  // Sync voice mode phase with agent status
  useEffect(() => {
    if (!voiceMode.active) return
    if (thinking) voiceMode.setPhase('thinking')
    else if (isStreaming) voiceMode.setPhase('speaking')
  }, [voiceMode.active, thinking, isStreaming])

  // Track artifact count (user clicks thumbnail to open preview)
  const prevArtifactsCount = useRef(0)
  useEffect(() => {
    prevArtifactsCount.current = artifacts.length
  }, [artifacts, artifactPanelOpen, setActiveArtifactId, setArtifactPanelOpen])

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
  }, [activeConversationId, searchParams, setMessages])

  // Fetch artifacts when thinking completes + poll for async generation (images take 30-60s)
  useEffect(() => {
    if (!thinking && loadedConvRef.current) {
      const cid = loadedConvRef.current
      const fetchArtifacts = () =>
        get<{ artifacts: Artifact[] }>(`/api/artifacts?conversation_id=${cid}`)
          .then(res => { if (res?.artifacts) setArtifacts(res.artifacts) })
          .catch(() => {})
      fetchArtifacts()
      // Poll every 5s for up to 90s to catch async image generation
      const interval = setInterval(fetchArtifacts, 5000)
      const timeout = setTimeout(() => clearInterval(interval), 90000)
      return () => { clearInterval(interval); clearTimeout(timeout) }
    }
  }, [thinking])

  // Auto-resize textarea
  useEffect(() => {
    const ta = textareaRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = Math.min(ta.scrollHeight, 200) + 'px'
  }, [inputValue])

  // Persist draft to localStorage
  useEffect(() => {
    if (inputValue) {
      localStorage.setItem('odigos-draft', inputValue)
    } else {
      localStorage.removeItem('odigos-draft')
    }
  }, [inputValue])

  // Timeout fallback for thinking state
  useEffect(() => {
    if (!thinking) return
    const timer = setTimeout(() => {
      setThinking(false)
      setStatus(null)
    }, 60000)
    return () => clearTimeout(timer)
  }, [thinking, status, setThinking, setStatus])

  // Check voice and agent settings (G-V5, G-V6)
  useEffect(() => {
    get<Record<string, any>>('/api/settings')
      .then((s) => {
        setSttAvailable(s.voice?.stt_provider !== 'disabled')
        setTtsAvailable(s.voice?.tts_provider !== 'disabled')
      })
      .catch(() => {})
  }, [])

  // Wire handleSendRef for voice mode auto-send
  useEffect(() => {
    handleSendRef.current = (text: string) => handleSend(text)
  })

  // TTS -- always use shared audio system from AppLayout via outlet context
  const playTTS = outletPlayTTS || (() => {})
  const stopTTS = outletStopTTS || (() => {})
  const isTTSPlaying = outletTTSPlaying ?? false

  const handleEdit = useCallback((messageIndex: number, content: string) => {
    socketRef.current?.send('edit', {
      message_index: messageIndex,
      content,
      conversation_id: activeConversationId,
    })
    // Truncate local messages state to match
    setMessages((prev: ChatMessage[]) => prev.slice(0, messageIndex))
  }, [activeConversationId, socketRef, setMessages])


  const getPreviousUserMessage = useCallback((assistantIndex: number): string => {
    for (let i = assistantIndex - 1; i >= 0; i--) {
      if (messages[i]?.role === 'user') return messages[i].content
    }
    return ''
  }, [messages])

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

  const removeFile = useCallback((file: File) => {
    setPendingFiles((prev) => prev.filter((p) => p.file !== file))
  }, [])

  const handleSend = useCallback((overrideContent?: string) => {
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
    setSuggestedActions([])

    socketRef.current?.send('chat', {
      content,
      conversation_id: activeConversationId || undefined,
      attachments: attachments.length > 0 ? attachments : undefined,
      context: chatContext,
    })

    setInputValue('')
    localStorage.removeItem('odigos-draft')
    setPendingFiles([])
  }, [inputValue, pendingFiles, activeConversationId, chatContext, socketRef, setMessages, setThinking, setSuggestedActions])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }, [handleSend])

  const canSend = connected && (inputValue.trim() || pendingFiles.length > 0) && queuedCount < 3 && !thinking

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
                  {voiceMode.active ? (
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
                        state={voiceMode.phase as any}
                        amplitude={voiceAmplitude}
                        onExit={() => voiceMode.exit()}
                        onToggleMic={() => {}}
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
                          {isStreaming && (
                            <div className="flex items-center gap-2 mt-3 pb-1 opacity-50 hover:opacity-100 transition-opacity duration-500">
                              <div className="size-1.5 bg-primary rounded-full animate-pulse" />
                              <span className="text-[11px] font-bold uppercase tracking-[0.15em] text-muted-foreground/80">
                                {status || 'Generating'}
                              </span>
                            </div>
                          )}
                        </div>
                      )}

                      {thinking && !streamingContent && (
                        <div className="flex items-center gap-2 py-3 animate-in fade-in duration-500">
                          <div className="flex gap-1">
                            <span className="h-2 w-2 rounded-full bg-muted-foreground/40 animate-bounce" style={{ animationDelay: '0ms', animationDuration: '1s' }} />
                            <span className="h-2 w-2 rounded-full bg-muted-foreground/40 animate-bounce" style={{ animationDelay: '200ms', animationDuration: '1s' }} />
                            <span className="h-2 w-2 rounded-full bg-muted-foreground/40 animate-bounce" style={{ animationDelay: '400ms', animationDuration: '1s' }} />
                          </div>
                          <span className="text-xs text-muted-foreground/60">
                            {status || 'Thinking...'}
                          </span>
                        </div>
                      )}

                      {artifacts.length > 0 && (
                        <div className="pt-2 mt-4">
                          <div className="flex flex-wrap gap-3">
                            {artifacts.map(a => (
                              a.content_type?.startsWith('image/') ? (
                                <ImageArtifact key={a.id} artifact={a} onClick={() => {
                                  setActiveArtifactId(a.id)
                                  setArtifactPanelOpen(true)
                                }} />
                              ) : (
                                <ArtifactCard key={a.id} artifact={a} />
                              )
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

            {/* Contextual Workspace Links (G-I6) */}
            <div className="flex items-center gap-3 px-1 mb-2">
              <button onClick={() => navigate('/notebooks')} className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground/50 hover:text-primary transition-colors">Journal</button>
              <span className="text-muted-foreground/20 text-[10px]">·</span>
              <button onClick={() => navigate('/kanban')} className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground/50 hover:text-primary transition-colors">Board</button>
              <span className="text-muted-foreground/20 text-[10px]">·</span>
              <button onClick={() => navigate('/images')} className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground/50 hover:text-primary transition-colors">Images</button>
              <span className="text-muted-foreground/20 text-[10px]">·</span>
              <button onClick={() => navigate('/artifacts')} className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground/50 hover:text-primary transition-colors">Documents</button>
            </div>

            {/* Composer */}
            <div className="relative rounded-2xl border border-border/50 bg-muted/30 focus-within:border-border/80 transition-colors shadow-sm">
              <textarea
                ref={textareaRef}
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={`Message ${agentName}...`}
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
                      aria-label={pushToTalk.recording ? "Tap to stop" : "Tap to speak"}
                      className={`h-11 w-11 lg:h-8 lg:w-8 rounded-lg transition-colors ${pushToTalk.recording ? 'bg-red-500 text-white animate-pulse' : 'text-muted-foreground hover:text-foreground'}`}
                      disabled={!connected}
                      onClick={() => {
                        stopTTS()
                        if (pushToTalk.recording) {
                          pushToTalk.stop()
                        } else {
                          pushToTalk.start()
                        }
                      }}
                    >
                      {pushToTalk.recording ? <Square className="h-4 w-4 lg:h-3.5 lg:w-3.5" /> : <Mic className="h-5 w-5 lg:h-4 lg:w-4" />}
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
                        stopTTS()
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
          </div>
        </div>
      </div>
    </FileUpload>
  )
})

ChatPanel.displayName = 'ChatPanel'
