import { useState } from 'react'
import { cn } from '@/lib/utils'
import type { NotebookEntry } from './NoteEntry'

interface NoteTableOfContentsProps {
  entries: NotebookEntry[]
  onJumpTo?: (entryId: string) => void
}

export function NoteTableOfContents({ entries, onJumpTo }: NoteTableOfContentsProps) {
  const [expanded, setExpanded] = useState(false)
  const dead = entries.filter((e) => e.status === 'dead').length
  const stale = entries.filter((e) => e.status === 'stale').length

  if (entries.length === 0) return null

  return (
    <div className="mb-3 rounded-xl bg-muted/20 border border-border">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-3 py-2 text-left flex items-center justify-between"
      >
        <span className="text-[10px] font-semibold text-muted-foreground tracking-wider uppercase">
          Contents · {entries.length} {entries.length === 1 ? 'note' : 'notes'}
          {dead > 0 && ` · ${dead} dead`}
          {stale > 0 && ` · ${stale} stale`}
        </span>
        <span className="text-xs text-muted-foreground">{expanded ? '−' : '+'}</span>
      </button>
      {expanded && (
        <div className="px-3 pb-2 space-y-1">
          {entries.map((entry, i) => {
            const preview = entry.content.slice(0, 60).replace(/\n/g, ' ')
            const time = new Date(entry.created_at).toLocaleTimeString([], {
              hour: '2-digit',
              minute: '2-digit',
            })
            return (
              <button
                key={entry.id}
                onClick={() => onJumpTo?.(entry.id)}
                className={cn(
                  'block w-full text-left text-xs text-muted-foreground hover:text-foreground',
                  entry.status === 'dead' && 'line-through',
                )}
              >
                {i + 1}. [{time} · agent] {preview}
                {entry.status === 'dead' && ' (dead)'}
                {entry.status === 'stale' && ' (stale)'}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
