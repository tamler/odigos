import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Search,
  MessageCircle,
  FileText,
  Columns3,
  Command,
  ArrowRight
} from 'lucide-react'
import * as Dialog from '@radix-ui/react-dialog'
import { get } from '@/lib/api'

interface SearchResult {
  id: string
  title: string
  type: 'conversation' | 'notebook' | 'board'
  updated_at: string
}

export function QuickSwitcher({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [selectedIndex, setSelectedIndex] = useState(0)
  const navigate = useNavigate()
  const abortRef = useRef<AbortController | null>(null)

  const handleSearch = useCallback(async (q: string) => {
    if (!q.trim()) {
      setResults([])
      return
    }

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    try {
      const encoded = encodeURIComponent(q.trim())
      const [convs, notes, boards] = await Promise.all([
        get<{ conversations: any[] }>(`/api/conversations/search?q=${encoded}&limit=10`),
        get<{ notebooks: any[] }>('/api/notebooks'),
        get<{ boards: any[] }>('/api/kanban/boards')
      ])

      if (controller.signal.aborted) return

      const lowerQ = q.toLowerCase()

      const all: SearchResult[] = [
        ...convs.conversations.map(c => ({
          id: c.id,
          title: c.title || `Chat ${new Date(c.started_at).toLocaleDateString()}`,
          type: 'conversation' as const,
          updated_at: c.last_message_at || c.started_at
        })),
        ...notes.notebooks
          .filter((n: any) => n.title.toLowerCase().includes(lowerQ))
          .map((n: any) => ({ id: n.id, title: n.title, type: 'notebook' as const, updated_at: n.updated_at })),
        ...boards.boards
          .filter((b: any) => b.title.toLowerCase().includes(lowerQ))
          .map((b: any) => ({ id: b.id, title: b.title, type: 'board' as const, updated_at: b.updated_at }))
      ]

      const sorted = all
        .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
        .slice(0, 10)

      setResults(sorted)
      setSelectedIndex(0)
    } catch (err) {
      if (!controller.signal.aborted) {
        console.error('Search failed', err)
      }
    }
  }, [])

  useEffect(() => {
    const timer = setTimeout(() => handleSearch(query), 300)
    return () => clearTimeout(timer)
  }, [query, handleSearch])

  useEffect(() => {
    if (!open) {
      setQuery('')
      setResults([])
      abortRef.current?.abort()
    }
  }, [open])

  const handleSelect = (item: SearchResult) => {
    const path = item.type === 'conversation' ? `/?c=${item.id}` :
                 item.type === 'notebook' ? `/notebooks/${item.id}` :
                 `/kanban/${item.id}`
    navigate(path)
    onOpenChange(false)
    setQuery('')
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSelectedIndex(prev => (prev + 1) % results.length)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSelectedIndex(prev => (prev - 1 + results.length) % results.length)
    } else if (e.key === 'Enter' && results[selectedIndex]) {
      handleSelect(results[selectedIndex])
    }
  }

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[100] bg-background/80 backdrop-blur-sm animate-in fade-in duration-200" />
        <Dialog.Content className="fixed left-[50%] top-[10%] lg:top-[20%] z-[101] w-[calc(100%-2rem)] max-w-lg translate-x-[-50%] gap-4 border border-border/40 bg-background p-0 shadow-2xl duration-200 animate-in zoom-in-95 rounded-2xl overflow-hidden">
          <div className="flex items-center px-4 py-3 border-b border-border/10">
            <Search className="h-4 w-4 mr-3 text-muted-foreground shrink-0" />
            <input
              autoFocus
              placeholder="Search workspaces, chats, notes..."
              value={query}
              onChange={e => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              className="flex-1 bg-transparent border-none outline-none text-base lg:text-sm placeholder:text-muted-foreground/50 min-w-0"
            />
            <div className="hidden lg:flex items-center gap-1 ml-2">
              <kbd className="pointer-events-none inline-flex h-5 select-none items-center gap-1 rounded border bg-muted px-1.5 font-mono text-[10px] font-medium text-muted-foreground opacity-100">
                Esc
              </kbd>
            </div>
          </div>

          <div className="max-h-[60vh] lg:max-h-[400px] overflow-y-auto py-2">
            {results.length > 0 ? (
              <div className="px-2">
                {results.map((item, i) => (
                  <button
                    key={`${item.type}-${item.id}`}
                    onClick={() => handleSelect(item)}
                    onMouseEnter={() => setSelectedIndex(i)}
                    className={`w-full flex items-center justify-between px-3 py-3 lg:py-2.5 rounded-xl text-sm transition-all min-h-[44px] ${i === selectedIndex ? 'bg-primary text-primary-foreground shadow-lg shadow-primary/20' : 'text-muted-foreground hover:bg-muted'}`}
                  >
                    <div className="flex items-center gap-3 overflow-hidden">
                      {item.type === 'conversation' && <MessageCircle className="h-4 w-4 shrink-0 opacity-70" />}
                      {item.type === 'notebook' && <FileText className="h-4 w-4 shrink-0 opacity-70" />}
                      {item.type === 'board' && <Columns3 className="h-4 w-4 shrink-0 opacity-70" />}
                      <span className="font-medium truncate">{item.title}</span>
                    </div>
                    <div className="flex items-center gap-2 shrink-0 ml-2">
                      <span className="text-[10px] opacity-50 uppercase tracking-widest font-bold hidden sm:inline">{item.type}</span>
                      {i === selectedIndex && <ArrowRight className="h-3 w-3" />}
                    </div>
                  </button>
                ))}
              </div>
            ) : query ? (
              <div className="px-4 py-8 text-center">
                <p className="text-sm text-muted-foreground">No results found for "{query}"</p>
              </div>
            ) : (
              <div className="px-4 py-8 text-center flex flex-col items-center gap-3">
                <div className="h-10 w-10 bg-muted rounded-full flex items-center justify-center">
                  <Command className="h-5 w-5 text-muted-foreground/50" />
                </div>
                <div>
                  <p className="text-sm font-medium">Quick Switcher</p>
                  <p className="text-xs text-muted-foreground">Type to search across Odigos</p>
                </div>
              </div>
            )}
          </div>

          <div className="hidden lg:flex px-4 py-2 border-t border-border/5 bg-muted/20 items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-1">
                <kbd className="h-4 w-4 rounded border bg-background flex items-center justify-center text-[10px] font-mono">↑</kbd>
                <kbd className="h-4 w-4 rounded border bg-background flex items-center justify-center text-[10px] font-mono">↓</kbd>
                <span className="text-[10px] text-muted-foreground uppercase font-bold tracking-tighter ml-1">Navigate</span>
              </div>
              <div className="flex items-center gap-1">
                <kbd className="h-4 w-7 rounded border bg-background flex items-center justify-center text-[10px] font-mono">↵</kbd>
                <span className="text-[10px] text-muted-foreground uppercase font-bold tracking-tighter ml-1">Open</span>
              </div>
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
