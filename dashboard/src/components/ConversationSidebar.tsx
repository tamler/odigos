import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Plus, MessageSquare } from 'lucide-react'
import { get } from '@/lib/api'

interface Conversation {
  id: string
  created_at: string
  message_count?: number
}

interface Props {
  activeId: string | null
  onSelect: (id: string | null) => void
}

export default function ConversationSidebar({ activeId, onSelect }: Props) {
  const [conversations, setConversations] = useState<Conversation[]>([])

  useEffect(() => {
    get<{ conversations: Conversation[] }>('/api/conversations?limit=50')
      .then((data) => setConversations(data.conversations))
      .catch(() => {})
  }, [])

  return (
    <div className="w-64 border-r flex flex-col bg-muted/30">
      <div className="p-3">
        <Button variant="outline" className="w-full justify-start gap-2" onClick={() => onSelect(null)}>
          <Plus className="h-4 w-4" /> New Chat
        </Button>
      </div>
      <div className="flex-1 overflow-y-auto px-2 space-y-1">
        {conversations.map((c) => (
          <button
            key={c.id}
            onClick={() => onSelect(c.id)}
            className={`w-full text-left px-3 py-2 rounded-lg text-sm flex items-center gap-2 transition-colors ${
              activeId === c.id ? 'bg-accent text-accent-foreground' : 'text-muted-foreground hover:bg-accent/50'
            }`}
          >
            <MessageSquare className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate">{c.id}</span>
          </button>
        ))}
      </div>
    </div>
  )
}
