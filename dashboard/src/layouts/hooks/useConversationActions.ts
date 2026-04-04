import { useState, useCallback, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { patch, del, getBlob } from '@/lib/api'
import { toast } from 'sonner'
import { useChatStore } from '@/stores/chatStore'
import { useUIStore } from '@/stores/uiStore'
import { useConversationStore } from '@/stores/conversationStore'
import type { Conversation } from '@/stores/conversationStore'

export function useConversationActions() {
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editTitle, setEditTitle] = useState('')
  const editInputRef = useRef<HTMLInputElement>(null)
  const navigate = useNavigate()

  const activeConversationId = useChatStore(s => s.activeConversationId)
  const setActiveConversationId = useChatStore(s => s.setActiveConversationId)

  useEffect(() => {
    if (editingId) editInputRef.current?.focus()
  }, [editingId])

  const handleNewChat = useCallback(() => {
    useChatStore.getState().setActiveConversationId(null)
    useChatStore.getState().setMessages([])
    useChatStore.getState().setStreamingContent('')
    useChatStore.getState().setThinking(false)
    useChatStore.getState().setStatus(null)
    useChatStore.getState().setSuggestedActions([])
    useUIStore.getState().setSidebarOpen(false)
    useConversationStore.getState().setSearchQuery('')
    navigate('/')
  }, [navigate])

  const handleSelectConversation = useCallback((id: string) => {
    useChatStore.getState().setActiveConversationId(id)
    useUIStore.getState().setSidebarOpen(false)
    useConversationStore.getState().setSearchQuery('')
    navigate(`/?c=${id}`)
  }, [navigate])

  const handleSelectImage = useCallback((id: string) => {
    useUIStore.getState().setActiveArtifactId(id)
    useUIStore.getState().setArtifactPanelOpen(true)
  }, [])

  const startRename = useCallback((c: Conversation | null) => {
    if (!c) {
      setEditingId(null)
      setEditTitle('')
      return
    }
    setEditingId(c.id)
    setEditTitle(c.title || c.id.slice(0, 8))
  }, [])

  const confirmRename = useCallback(async () => {
    if (!editingId || !editTitle.trim()) { setEditingId(null); return }
    try {
      await patch(`/api/conversations/${editingId}`, { title: editTitle.trim() })
      useConversationStore.getState().setConversations((prev) => prev.map((c) => (c.id === editingId ? { ...c, title: editTitle.trim() } : c)))
    } catch { toast.error('Failed to rename conversation') }
    setEditingId(null)
  }, [editingId, editTitle])

  const handleDelete = useCallback(async (id: string) => {
    try {
      await del(`/api/conversations/${id}`)
      useConversationStore.getState().setConversations((prev) => prev.filter((c) => c.id !== id))
      if (activeConversationId === id) { setActiveConversationId(null); navigate('/') }
      toast.success('Conversation deleted')
    } catch { toast.error('Failed to delete conversation') }
  }, [activeConversationId, navigate, setActiveConversationId])

  const handleExport = useCallback((id: string, format: 'markdown' | 'json') => {
    const url = `/api/conversations/${id}/export?format=${format}`
    getBlob(url).then(blob => {
      const ext = format === 'json' ? 'json' : 'md'
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = `${id}.${ext}`
      a.click()
      URL.revokeObjectURL(a.href)
      toast.success('Conversation exported')
    }).catch(() => toast.error('Failed to export conversation'))
  }, [])

  const displayTitle = useCallback((c: Conversation): string => {
    if (c.title) return c.title
    const raw = c.last_message_at || c.started_at
    if (!raw) return 'New chat'
    const date = new Date(raw + 'Z')
    return `Chat ${date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}`
  }, [])

  return {
    editingId,
    editTitle,
    setEditTitle,
    editInputRef,
    handleNewChat,
    handleSelectConversation,
    handleSelectImage,
    startRename,
    confirmRename,
    handleDelete,
    handleExport,
    displayTitle,
  }
}
