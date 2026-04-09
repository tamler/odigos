import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { Todo } from '@/hooks/useActivityData'

interface TodosSectionProps {
  todos: Todo[]
  error: string | null
  onComplete: (id: string) => Promise<void>
}

function dueText(todo: Todo): { text: string; overdue: boolean } {
  if (!todo.scheduled_at) return { text: 'no due date', overdue: false }
  const due = new Date(todo.scheduled_at).getTime()
  const now = Date.now()
  const diffMs = due - now

  if (diffMs < 0) {
    const overdueMs = -diffMs
    const minutes = Math.floor(overdueMs / 60000)
    if (minutes < 60) return { text: `${minutes}m overdue`, overdue: true }
    const hours = Math.floor(minutes / 60)
    if (hours < 24) return { text: `${hours}h overdue`, overdue: true }
    const days = Math.floor(hours / 24)
    return { text: `${days}d overdue`, overdue: true }
  }

  const dueDate = new Date(todo.scheduled_at)
  const today = new Date()
  if (dueDate.toDateString() === today.toDateString()) {
    return { text: 'today', overdue: false }
  }
  const tomorrow = new Date(today.getTime() + 86400000)
  if (dueDate.toDateString() === tomorrow.toDateString()) {
    return { text: 'tomorrow', overdue: false }
  }
  return { text: dueDate.toLocaleDateString(), overdue: false }
}

function sortTodos(todos: Todo[]): Todo[] {
  return [...todos].sort((a, b) => {
    const aTime = a.scheduled_at ? new Date(a.scheduled_at).getTime() : Infinity
    const bTime = b.scheduled_at ? new Date(b.scheduled_at).getTime() : Infinity
    return aTime - bTime
  })
}

export function TodosSection({ todos, error, onComplete }: TodosSectionProps) {
  const navigate = useNavigate()
  const [expanded, setExpanded] = useState(false)

  if (error) return null

  const sorted = sortTodos(todos)
  const visible = expanded ? sorted : sorted.slice(0, 5)
  const hasMore = sorted.length > 5

  return (
    <section className="mb-6">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-[10px] font-semibold tracking-widest text-muted-foreground uppercase">
          Todos
        </h2>
        {hasMore && (
          <button
            onClick={() => setExpanded(!expanded)}
            className="text-xs text-muted-foreground hover:text-foreground"
          >
            {expanded ? 'show less' : `view all (${sorted.length})`}
          </button>
        )}
      </div>
      {sorted.length === 0 ? (
        <div className="text-sm text-muted-foreground">
          No pending todos. Add one in chat.
        </div>
      ) : (
        <div className="space-y-1">
          {visible.map((todo) => {
            const due = dueText(todo)
            return (
              <div
                key={todo.id}
                className="flex items-center gap-3 p-2 rounded-lg hover:bg-muted/50"
              >
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    void onComplete(todo.id)
                  }}
                  className="size-4 border border-border rounded hover:bg-primary hover:border-primary transition-colors flex-shrink-0"
                  aria-label="Mark complete"
                />
                <button
                  onClick={() => navigate(`/?c=new&about=todo:${todo.id}`)}
                  className="flex-1 text-left text-sm truncate"
                >
                  {todo.description}
                </button>
                <div
                  className={`text-xs tabular-nums whitespace-nowrap ${
                    due.overdue
                      ? 'text-red-500 dark:text-red-400'
                      : 'text-muted-foreground'
                  }`}
                >
                  {due.text}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}
