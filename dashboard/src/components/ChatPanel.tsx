import { useEffect, useRef, useState, useCallback, memo } from 'react'
import { useSearchParams, useOutletContext } from 'react-router-dom'
import { ChatSocket } from '@/lib/ws'
import { get, uploadFile } from '@/lib/api'
import { toast } from 'sonner'
import { PanelRightClose } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { FileUpload, FileUploadContent } from '@/components/ui/file-upload'
import { Artifact } from '@/components/ArtifactCard'
import { useVoiceMode } from '@/hooks/useVoiceMode'
import { usePushToTalk } from '@/hooks/usePushToTalk'
import type { ChatMessage } from '@/layouts/AppLayout'
import { useChatStore } from '@/stores/chatStore'
import { useUIStore } from '@/stores/uiStore'
import { MessageDisplay } from '@/components/chat/MessageDisplay'
import { SuggestedActions } from '@/components/chat/SuggestedActions'
import { ChatInputArea } from '@/components/chat/ChatInputArea'

interface ChatPanelProps {
  activeConversationId: string | null
  socketRef: React.MutableRefObject<ChatSocket | null>
  connected: boolean
  chatContext?: Record<string, string>
  isSidePanel?: boolean
  onClose?: () => void
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

  let outletCtx: any = {}
  try { outletCtx = useOutletContext<any>() || {} } catch { outletCtx = {} }
  const {
    playTTS: outletPlayTTS,
    stopTTS: outletStopTTS,
    isTTSPlaying: outletTTSPlaying,
  } = outletCtx

  const messages = useChatStore(s => s.messages)
  const setMessages = useChatStore(s => s.setMessages)
  const streamingContent = useChatStore(s => s.streamingContent)
  const thinking = useChatStore(s => s.thinking)
  const status = useChatStore(s => s.status)
  const queuedCount = useChatStore(s => s.queuedCount)
  const suggestedActions = useChatStore(s => s.suggestedActions)
  const isStreaming = useChatStore(s => s.isStreaming)

  const isMobile = useUIStore(s => s.isMobile)
  const setArtifactPanelOpen = useUIStore(s => s.setArtifactPanelOpen)
  const setActiveArtifactId = useUIStore(s => s.setActiveArtifactId)
  const agentName = useUIStore(s => s.agentName)
  const hasNewEmail = useUIStore(s => s.hasNewEmail)

  const [messageDisplayLimit, setMessageDisplayLimit] = useState(100)
  const [artifacts, setArtifacts] = useState<Artifact[]>([])
  const [inputValue, setInputValue] = useState(
    () => localStorage.getItem('odigos-draft') || ''
  )
  const [pendingFiles, setPendingFiles] = useState<{ file: File; id?: string; uploading?: boolean; progress?: number }[]>([])
  const [sttAvailable, setSttAvailable] = useState(false)
  const [ttsAvailable, setTtsAvailable] = useState(false)
  const [showAllActions, setShowAllActions] = useState(false)
  const [useCamera, setUseCamera] = useState<boolean | 'environment'>(false)
  const [voiceAmplitude, setVoiceAmplitude] = useState(0)
  const [switchingConversation, setSwitchingConversation] = useState(false)
  const loadedConvRef = useRef<string | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const voiceMode = useVoiceMode({
    onTranscription: (text) => {
      handleSendRef.current?.(text)
    },
    onPhaseChange: (_phase) => {},
    onAmplitudeChange: setVoiceAmplitude,
  })
  const handleSendRef = useRef<((text: string) => void) | null>(null)

  const pushToTalk = usePushToTalk((text) => {
    setInputValue(prev => prev ? `${prev} ${text}` : text)
  })

  useEffect(() => {
    const handler = (e: Event) => {
      const msg = (e as CustomEvent).detail
      if (msg) toast.error(msg)
    }
    window.addEventListener('voice-error', handler)
    return () => window.removeEventListener('voice-error', handler)
  }, [])

  // Safety: clear all states after 300s if server never responds
  // Music generation (submit_music) can take up to 240s, so 120s was too short
  useEffect(() => {
    if (!thinking) return
    const timer = setTimeout(() => {
      useChatStore.getState().setThinking(false)
      useChatStore.getState().setStatus(null)
    }, 300000)
    return () => clearTimeout(timer)
  }, [thinking])

  // Sync voice mode phase with agent status
  useEffect(() => {
    if (!voiceMode.active) return
    if (thinking) voiceMode.setPhase('thinking')
    else if (isStreaming) voiceMode.setPhase('speaking')
  }, [voiceMode.active, thinking, isStreaming])

  const prevArtifactsCount = useRef(0)
  useEffect(() => {
    prevArtifactsCount.current = artifacts.length
  }, [artifacts, setActiveArtifactId, setArtifactPanelOpen])

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
    setSwitchingConversation(true)

    useChatStore.getState().setThinking(false)
    useChatStore.getState().setStatus(null)

    Promise.allSettled([
      get<{ messages: { role: string; content: string; timestamp: string }[] }>(`/api/conversations/${cid}/messages?limit=50&offset=0`),
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
      setSwitchingConversation(false)
    }).catch(() => { setSwitchingConversation(false) })
  }, [activeConversationId, searchParams, setMessages])

  // Fetch artifacts when thinking completes or new messages arrive
  // messages.length covers the case where thinking times out before a long-running
  // tool (e.g. music gen ~240s) finishes — the chat_response adds a message,
  // triggering a refetch even though thinking was already false
  useEffect(() => {
    if (!thinking && loadedConvRef.current) {
      const cid = loadedConvRef.current
      const fetchArtifacts = () =>
        get<{ artifacts: Artifact[] }>(`/api/artifacts?conversation_id=${cid}`)
          .then(res => { if (res?.artifacts) setArtifacts(res.artifacts) })
          .catch(() => {})
      fetchArtifacts()
      const timer = setTimeout(fetchArtifacts, 5000)
      return () => clearTimeout(timer)
    }
  }, [thinking, messages.length])

  useEffect(() => {
    const ta = textareaRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = Math.min(ta.scrollHeight, 200) + 'px'
  }, [inputValue])

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
      useChatStore.getState().setThinking(false)
      useChatStore.getState().setStatus(null)
    }, 60000)
    return () => clearTimeout(timer)
  }, [thinking, status])

  useEffect(() => {
    get<Record<string, any>>('/api/settings')
      .then((s) => {
        setSttAvailable(s.voice?.stt_provider !== 'disabled')
        setTtsAvailable(s.voice?.tts_provider !== 'disabled')
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    handleSendRef.current = (text: string) => handleSend(text)
  })

  const playTTS = outletPlayTTS || (() => {})
  const stopTTS = outletStopTTS || (() => {})
  const isTTSPlaying = outletTTSPlaying ?? false

  const handleEdit = useCallback((messageIndex: number, content: string) => {
    socketRef.current?.send('edit', {
      message_index: messageIndex,
      content,
      conversation_id: activeConversationId,
    })
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
    useChatStore.getState().setThinking(true)
    useChatStore.getState().setSuggestedActions([])

    socketRef.current?.send('chat', {
      content,
      conversation_id: activeConversationId || 'new',
      attachments: attachments.length > 0 ? attachments : undefined,
      context: chatContext,
    })

    setInputValue('')
    localStorage.removeItem('odigos-draft')
    setPendingFiles([])
  }, [inputValue, pendingFiles, activeConversationId, chatContext, socketRef, setMessages])

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
        {onClose && (
          <div className="flex items-center justify-end px-4 h-[40px] shrink-0">
            <Button variant="ghost" size="icon" aria-label="Close chat panel" onClick={onClose} className="shrink-0 h-8 w-8 hover:bg-muted">
              <PanelRightClose className="h-4 w-4" />
            </Button>
          </div>
        )}

        <FileUploadContent>
          <div className="rounded-xl border-2 border-dashed border-primary/50 bg-primary/5 p-12 text-center">
            <p className="text-lg font-medium text-primary">Drop files here</p>
            <p className="text-sm text-muted-foreground mt-1">Files will be uploaded and attached to your message</p>
          </div>
        </FileUploadContent>

        <MessageDisplay
          messages={messages}
          streamingContent={streamingContent}
          thinking={thinking}
          status={status}
          artifacts={artifacts}
          messageDisplayLimit={messageDisplayLimit}
          switchingConversation={switchingConversation}
          voiceMode={{
            active: voiceMode.active,
            phase: voiceMode.phase,
            exit: voiceMode.exit,
          }}
          voiceAmplitude={voiceAmplitude}
          isStreaming={isStreaming}
          ttsAvailable={ttsAvailable}
          activeConversationId={activeConversationId}
          agentName={agentName}
          isSidePanel={isSidePanel}
          socket={socketRef.current}
          playTTS={playTTS}
          stopTTS={stopTTS}
          isTTSPlaying={isTTSPlaying}
          onLoadMore={() => setMessageDisplayLimit(l => l + 100)}
          onEdit={handleEdit}
          onOpenArtifact={(id) => {
            setActiveArtifactId(id)
            setArtifactPanelOpen(true)
          }}
          onSuggest={(text) => handleSend(text)}
          getPreviousUserMessage={getPreviousUserMessage}
        />

        <SuggestedActions
          actions={suggestedActions}
          showAll={showAllActions}
          onToggleShowAll={() => setShowAllActions(!showAllActions)}
          activeConversationId={activeConversationId}
          socketRef={socketRef}
          setMessages={setMessages}
          isSidePanel={isSidePanel}
        />

        <ChatInputArea
          inputValue={inputValue}
          setInputValue={setInputValue}
          pendingFiles={pendingFiles}
          onSend={handleSend}
          onRemoveFile={removeFile}
          onKeyDown={handleKeyDown}
          textareaRef={textareaRef}
          connected={connected}
          canSend={!!canSend}
          isStreaming={isStreaming}
          sttAvailable={sttAvailable}
          setUseCamera={setUseCamera}
          agentName={agentName}
          isSidePanel={isSidePanel}
          hasNewEmail={hasNewEmail}
          isMobile={isMobile}
          pushToTalk={pushToTalk}
          socketRef={socketRef}
          stopTTS={stopTTS}
          onEmailClick={() => {
            useUIStore.getState().setHasNewEmail(false)
            handleSend('Check my email')
          }}
        />
      </div>
    </FileUpload>
  )
})

ChatPanel.displayName = 'ChatPanel'
