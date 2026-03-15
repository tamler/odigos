import { useState, useEffect, useCallback } from 'react'
import { get, put } from '@/lib/api'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { ChevronDown, ChevronRight, FileText, Cog } from 'lucide-react'

interface Prompt {
  name: string
  directory: string
  path: string
}

interface PromptContent {
  name: string
  directory: string
  content: string
}

function PromptCard({
  prompt,
  onSaved,
}: {
  prompt: Prompt
  onSaved: () => void
}) {
  const [expanded, setExpanded] = useState(false)
  const [content, setContent] = useState<string | null>(null)
  const [editContent, setEditContent] = useState('')
  const [editing, setEditing] = useState(false)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)

  async function loadContent() {
    if (content !== null) return
    setLoading(true)
    try {
      const data = await get<PromptContent>(
        `/api/prompts/${prompt.directory}/${prompt.name}`
      )
      setContent(data.content)
      setEditContent(data.content)
    } catch {
      toast.error('Failed to load prompt')
    } finally {
      setLoading(false)
    }
  }

  function handleExpand() {
    const next = !expanded
    setExpanded(next)
    if (next) loadContent()
  }

  async function handleSave() {
    setSaving(true)
    try {
      await put(`/api/prompts/${prompt.directory}/${prompt.name}`, {
        content: editContent,
      })
      toast.success(`Prompt "${prompt.name}" updated`)
      setContent(editContent)
      setEditing(false)
      onSaved()
    } catch {
      toast.error('Failed to update prompt')
    } finally {
      setSaving(false)
    }
  }

  function handleCancel() {
    setEditContent(content || '')
    setEditing(false)
  }

  const isAgent = prompt.directory === 'agent'

  return (
    <div className="rounded-lg border border-border/40 bg-card">
      <div
        className="flex items-center justify-between px-4 py-3 cursor-pointer"
        onClick={handleExpand}
      >
        <div className="flex items-center gap-2 min-w-0">
          {expanded ? (
            <ChevronDown className="h-4 w-4 text-muted-foreground shrink-0" />
          ) : (
            <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" />
          )}
          {isAgent ? (
            <FileText className="h-3.5 w-3.5 text-primary shrink-0" />
          ) : (
            <Cog className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
          )}
          <span className="text-sm font-medium truncate">{prompt.name}</span>
          <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
            {prompt.directory}
          </span>
        </div>
      </div>

      {expanded && (
        <div className="px-4 pb-4 space-y-3 border-t border-border/40 pt-3">
          {loading ? (
            <p className="text-sm text-muted-foreground">Loading...</p>
          ) : editing ? (
            <>
              <textarea
                value={editContent}
                onChange={(e) => setEditContent(e.target.value)}
                rows={12}
                className="w-full rounded-md border border-border/40 bg-muted/50 px-3 py-2 text-sm font-mono resize-y focus:outline-none focus:ring-1 focus:ring-ring"
              />
              <div className="flex gap-2">
                <Button size="sm" onClick={handleSave} disabled={saving}>
                  {saving ? 'Saving...' : 'Save'}
                </Button>
                <Button size="sm" variant="ghost" onClick={handleCancel}>
                  Cancel
                </Button>
              </div>
            </>
          ) : (
            <>
              <div className="rounded-md bg-muted/50 p-3">
                <pre className="text-xs text-foreground whitespace-pre-wrap font-mono">
                  {content}
                </pre>
              </div>
              <Button
                size="sm"
                variant="outline"
                onClick={() => setEditing(true)}
              >
                Edit
              </Button>
            </>
          )}
        </div>
      )}
    </div>
  )
}

export default function PromptsTab() {
  const [prompts, setPrompts] = useState<Prompt[]>([])

  const load = useCallback(async () => {
    try {
      const data = await get<Prompt[]>('/api/prompts')
      setPrompts(data)
    } catch {
      toast.error('Failed to load prompts')
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const agentPrompts = prompts.filter((p) => p.directory === 'agent')
  const infraPrompts = prompts.filter((p) => p.directory === 'prompts')

  return (
    <div className="max-w-3xl mx-auto px-6 py-6 space-y-5">
      <p className="text-sm text-muted-foreground">
        Editable prompt files that shape the agent's behavior. Agent prompts
        define the system personality. Infrastructure prompts are templates used
        by internal subsystems.
      </p>

      {agentPrompts.length > 0 && (
        <div className="space-y-3">
          <h2 className="text-sm font-medium text-muted-foreground">
            Agent Identity
          </h2>
          <div className="space-y-2">
            {agentPrompts.map((p) => (
              <PromptCard
                key={`${p.directory}/${p.name}`}
                prompt={p}
                onSaved={load}
              />
            ))}
          </div>
        </div>
      )}

      {infraPrompts.length > 0 && (
        <div className="space-y-3">
          <h2 className="text-sm font-medium text-muted-foreground">
            Infrastructure
          </h2>
          <div className="space-y-2">
            {infraPrompts.map((p) => (
              <PromptCard
                key={`${p.directory}/${p.name}`}
                prompt={p}
                onSaved={load}
              />
            ))}
          </div>
        </div>
      )}

      {prompts.length === 0 && (
        <p className="text-sm text-muted-foreground text-center py-8">
          No prompt files found.
        </p>
      )}

      <div className="h-4" />
    </div>
  )
}
