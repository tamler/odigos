import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTheme } from 'next-themes'
import { toast } from 'sonner'
import { ChatSocket } from '@/lib/ws'
import { executeActions, UIAction } from '@/lib/actions'
import { stripForTTS, shouldPlayTTS } from '@/lib/tts-filter'
import { useAudio } from '@/hooks/useAudio'
import { useDriver } from '@/hooks/useDriver'
import { subscribeToPush } from '@/lib/push'
import { useChatStore } from '@/stores/chatStore'
import { useUIStore } from '@/stores/uiStore'
import { useConversationStore } from '@/stores/conversationStore'

export function useWebSocketHandler(pendingTitles: React.MutableRefObject<Record<string, string>>) {
  const socketRef = useRef<ChatSocket | null>(null)
  const chunkBufferRef = useRef('')
  const chunkFlushTimerRef = useRef<number | null>(null)
  const navigate = useNavigate()
  const navigateRef = useRef(navigate)
  navigateRef.current = navigate
  const { setTheme } = useTheme()
  const setThemeRef = useRef(setTheme)
  setThemeRef.current = setTheme

  const activeConversationId = useChatStore(s => s.activeConversationId)
  const activeIdRef = useRef(activeConversationId)
  useEffect(() => {
    activeIdRef.current = activeConversationId
  }, [activeConversationId])

  const { play: playTTS, stop: stopTTS, playing: isTTSPlaying } = useAudio()
  const { highlight: driverHighlight } = useDriver()

  useEffect(() => {
    const socket = new ChatSocket(
      (msg) => {
        const chat = useChatStore.getState()
        const ui = useUIStore.getState()

        if (msg.type === 'notification') {
          const body = (msg.body || msg.message || '') as string
          const title = msg.title as string | undefined
          const label = title ? `${title}: ${body}` : body
          const priority = (msg.priority || 'info') as string
          if (title?.toLowerCase().includes('email')) ui.setHasNewEmail(true)
          if (priority === 'urgent') toast.error(label)
          else if (priority === 'warning') toast.warning(label)
          else toast.info(label)
        }
        if (msg.type === 'status') chat.setStatus(msg.text as string)
        if (msg.type === 'chat_chunk') {
          if (msg.conversation_id && activeIdRef.current && msg.conversation_id !== activeIdRef.current) return
          chat.setThinking(false)
          chat.setStatus(null)

          // Throttled in-place streaming: buffer chunks, flush every 50ms.
          // Prevents dozens of re-renders per second and Markdown re-parsing on every token.
          chunkBufferRef.current += (msg.content as string)

          if (!chunkFlushTimerRef.current) {
            chunkFlushTimerRef.current = window.setTimeout(() => {
              const buffered = chunkBufferRef.current
              chunkBufferRef.current = ''
              chunkFlushTimerRef.current = null
              if (!buffered) return

              const state = useChatStore.getState()
              const lastMsg = state.messages.length > 0 ? state.messages[state.messages.length - 1] : null
              if (lastMsg && lastMsg.role === 'assistant' && state.isStreaming) {
                chat.appendToLastMessage(buffered)
              } else {
                chat.setMessages((prev) => [...prev, {
                  role: 'assistant' as const,
                  content: buffered,
                  timestamp: new Date().toISOString(),
                }])
                chat.startStreaming()
              }
            }, 50)
          }
        }
        if (msg.type === 'chat_response') {
          if (msg.conversation_id && activeIdRef.current && msg.conversation_id !== activeIdRef.current) return
          if (!activeIdRef.current && msg.conversation_id) {
            const newId = msg.conversation_id as string
            const chatId = newId.includes(':') ? newId.split(':')[1] : newId
            chat.setActiveConversationId(chatId)
          }
          // Flush any buffered chunks before finalizing
          if (chunkFlushTimerRef.current) {
            clearTimeout(chunkFlushTimerRef.current)
            chunkFlushTimerRef.current = null
          }
          if (chunkBufferRef.current) {
            chat.appendToLastMessage(chunkBufferRef.current)
            chunkBufferRef.current = ''
          }
          chat.setThinking(false)
          chat.setStatus(null)
          if (useChatStore.getState().isStreaming) {
            chat.finalizeLastMessage()
          } else if (msg.content) {
            chat.addMessage({
              role: 'assistant',
              content: msg.content as string,
              timestamp: new Date().toISOString(),
            })
          }
          const msgs = useChatStore.getState().messages
          const finalContent = msgs.length > 0 ? msgs[msgs.length - 1].content : ''
          if (ui.focusMode && finalContent && shouldPlayTTS(finalContent)) {
            playTTS(stripForTTS(finalContent))
          }
          if (Array.isArray(msg.actions) && msg.actions.length > 0) {
            executeActions(msg.actions as UIAction[], navigateRef.current, {
              refresh: () => useConversationStore.getState().refreshConversations(),
              openChat: () => ui.setChatPanelOpen(true),
              setTheme: (t) => setThemeRef.current(t),
              stopTTS,
              highlight: driverHighlight,
            })
          }
        }
        if (msg.type === 'stream_end') {
          // Flush remaining buffer
          if (chunkFlushTimerRef.current) {
            clearTimeout(chunkFlushTimerRef.current)
            chunkFlushTimerRef.current = null
          }
          if (chunkBufferRef.current) {
            chat.appendToLastMessage(chunkBufferRef.current)
            chunkBufferRef.current = ''
          }
          chat.finalizeLastMessage()
        }
        if (msg.type === 'queue_update') {
          const queued = msg.queued as number
          chat.setQueuedCount(queued)
          if (queued === 0) chat.setThinking(false)
        }
        if (msg.type === 'message_queued') chat.setStatus(`Queued (${msg.queued as number} pending)`)
        if (msg.type === 'queue_full') toast.warning('Message queue is full. Please wait.')
        if (msg.type === 'suggested_actions' && msg.actions) chat.setSuggestedActions(msg.actions as string[])
        if (msg.type === 'title_updated' && msg.conversation_id && msg.title) {
          const cid = msg.conversation_id as string
          const title = msg.title as string
          pendingTitles.current[cid] = title
          useConversationStore.getState().setConversations((prev) => prev.map((c) => (c.id === cid ? { ...c, title } : c)))
        }
        if (msg.type === 'feed_update') toast.info(`New feed items from ${msg.source || 'RSS feed'}`, { duration: 4000 })
        if (msg.type === 'email_received') {
          ui.setHasNewEmail(true)
          toast.info(`New email: ${msg.subject || 'New message'}`, { duration: 5000 })
        }
        if (msg.type === 'task_started' && msg.task) {
          const task = msg.task as any
          ui.addBackgroundTask({
            id: task.id,
            toolName: task.tool_name,
            description: task.description,
            startedAt: task.started_at,
            conversationId: msg.conversation_id as string,
          })
        }
        if (msg.type === 'task_completed') {
          ui.removeBackgroundTask(msg.task_id as string)
          const toolLabel = (msg.tool_name as string)?.replace('generate_', '') || 'Task'
          const resultText = msg.result as string || 'Ready'
          toast.success(`${toolLabel} complete: ${resultText}`, { duration: 5000 })

          // Add system message to chat if it's the active conversation
          if (msg.conversation_id === activeIdRef.current) {
            chat.setMessages((prev) => [...prev, {
              role: 'system',
              content: `[Background task completed] ${resultText}`,
              timestamp: new Date().toISOString(),
            }])
          }
          // Refresh conversation list to update message counts/last activity
          useConversationStore.getState().refreshConversations()
        }
      },
      (isConnected) => {
        const wasConnected = useUIStore.getState().connected
        useUIStore.getState().setConnected(isConnected)
        if (isConnected && !wasConnected) toast.dismiss()
        if (!isConnected && wasConnected) toast('Reconnecting...', { duration: 3000 })
      },
    )
    socket.connect()
    socketRef.current = socket

    if (typeof Notification !== 'undefined') {
      if (Notification.permission === 'default') {
        Notification.requestPermission().then((perm) => {
          if (perm === 'granted') subscribeToPush()
        }).catch(() => {})
      } else if (Notification.permission === 'granted') {
        subscribeToPush()
      }
    }

    return () => socket.disconnect()
  }, [playTTS])

  return { socketRef, playTTS, stopTTS, isTTSPlaying, driverHighlight }
}
