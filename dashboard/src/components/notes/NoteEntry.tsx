import { useState } from 'react'
import Markdown from 'react-markdown'
import { cn } from '@/lib/utils'

export interface NotebookEntry {
  id: string
  notebook_id: string
  content: string
  entry_type: 'user' | 'agent' | 'agent_suggestion'
  status: 'active' | 'rejected' | 'dead' | 'stale'
  quote: string | null
  trigger_type: string | null
  viewed_at: string | null
  created_at: string
  parent_id: string | null
}

interface NoteEntryProps {
  entry: NotebookEntry
  onQuoteClick?: (quote: string) => void
  onReplyClick?: (entry: NotebookEntry) => void
  onToggleDead?: (entry: NotebookEntry) => void
}

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime()
  const now = Date.now()
  const diff = now - then
  const min = Math.floor(diff / 60000)
  if (min < 1) return 'just now'
  if (min < 60) return `${min}m ago`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr}h ago`
  const day = Math.floor(hr / 24)
  return `${day}d ago`
}

export function NoteEntry({ entry, onQuoteClick, onReplyClick, onToggleDead }: NoteEntryProps) {
  const isUnread = !entry.viewed_at && entry.status === 'active'
  const isDead = entry.status === 'dead'
  const isStale = entry.status === 'stale'
  const [expanded, setExpanded] = useState(!isDead)

  return (
    <div
      data-note-id={entry.id}
      className={cn(
        'rounded-xl p-3 mb-2 border-l-2 border border-border bg-card transition-opacity',
        'border-l-purple-400',
        isDead && 'opacity-50',
        isStale && 'opacity-70',
      )}
    >
      <div className="flex items-center gap-2 mb-1">
        {isUnread && <div className="size-1.5 rounded-full bg-purple-400" aria-label="unread" />}
        <span className="text-[10px] font-semibold text-muted-foreground tracking-wider uppercase">
          AGENT
        </span>
        {entry.trigger_type && (
          <span className="text-[10px] text-muted-foreground">
            · {entry.trigger_type}
          </span>
        )}
        <span className="text-[10px] text-muted-foreground">
          · {relativeTime(entry.created_at)}
        </span>
        {isDead && (
          <span className="text-[10px] text-muted-foreground">· dead</span>
        )}
        {isStale && (
          <span className="text-[10px] text-muted-foreground">· stale quote</span>
        )}
        {isDead && (
          <button
            onClick={() => setExpanded(!expanded)}
            className="ml-auto text-[10px] text-muted-foreground hover:text-foreground"
          >
            {expanded ? 'collapse' : 'expand'}
          </button>
        )}
      </div>

      {expanded && (
        <>
          {entry.quote && (
            <button
              onClick={() => onQuoteClick?.(entry.quote!)}
              className={cn(
                'block w-full text-left border-l-2 border-muted-foreground/40 pl-2 my-2',
                'text-xs italic text-muted-foreground hover:text-foreground transition-colors',
                isStale && 'line-through',
              )}
              disabled={isStale}
            >
              "{entry.quote}"
              {isStale && <span className="ml-2 not-italic">[quote no longer in document]</span>}
            </button>
          )}
          <div className="text-sm prose prose-invert prose-sm max-w-none">
            <Markdown>{entry.content}</Markdown>
          </div>
          <div className="flex gap-3 mt-2 text-xs">
            {!isDead && onReplyClick && (
              <button
                onClick={() => onReplyClick(entry)}
                className="text-primary hover:underline"
              >
                Reply
              </button>
            )}
            {onToggleDead && (
              <button
                onClick={() => onToggleDead(entry)}
                className="text-muted-foreground hover:text-foreground"
              >
                {isDead ? 'Mark active' : 'Mark dead'}
              </button>
            )}
          </div>
        </>
      )}
    </div>
  )
}
