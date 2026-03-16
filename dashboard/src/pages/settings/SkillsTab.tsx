import { useState, useEffect, useCallback } from 'react'
import { get, post, del } from '@/lib/api'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Plus, Trash2, ChevronDown, ChevronRight, Lock } from 'lucide-react'

interface Skill {
  name: string
  description: string
  tools: string[]
  complexity: string
  system_prompt: string
  builtin: boolean
}

function SkillCard({
  skill,
  onSaved,
  onDeleted,
}: {
  skill: Skill
  onSaved: () => void
  onDeleted: () => void
}) {
  const [expanded, setExpanded] = useState(false)
  const [editing, setEditing] = useState(false)
  const [description, setDescription] = useState(skill.description)
  const [systemPrompt, setSystemPrompt] = useState(skill.system_prompt)
  const [tools, setTools] = useState(skill.tools.join(', '))
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)

  async function handleSave() {
    setSaving(true)
    try {
      await fetch(`/api/skills/${skill.name}`, {
        method: 'PUT',
        headers: {
          Authorization: `Bearer ${localStorage.getItem('odigos_api_key') || ''}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          description,
          system_prompt: systemPrompt,
          tools: tools
            .split(',')
            .map((t) => t.trim())
            .filter(Boolean),
        }),
      })
      toast.success(`Skill "${skill.name}" updated`)
      setEditing(false)
      onSaved()
    } catch {
      toast.error('Failed to update skill')
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete() {
    setDeleting(true)
    try {
      await del(`/api/skills/${skill.name}`)
      toast.success(`Skill "${skill.name}" deleted`)
      onDeleted()
    } catch {
      toast.error('Failed to delete skill')
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="rounded-lg border border-border/40 bg-card">
      <div
        className="flex items-center justify-between px-4 py-3 cursor-pointer"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-2 min-w-0">
          {expanded ? (
            <ChevronDown className="h-4 w-4 text-muted-foreground shrink-0" />
          ) : (
            <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" />
          )}
          <span className="text-sm font-medium truncate">{skill.name}</span>
          {skill.builtin && <Lock className="h-3 w-3 text-muted-foreground shrink-0" />}
          <span className="text-xs text-muted-foreground truncate">{skill.description}</span>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {skill.tools.length > 0 && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary border border-primary/20">
              {skill.tools.length} tool{skill.tools.length !== 1 ? 's' : ''}
            </span>
          )}
        </div>
      </div>

      {expanded && (
        <div className="px-4 pb-4 space-y-3 border-t border-border/40 pt-3">
          {editing && !skill.builtin ? (
            <>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">Description</Label>
                <Input
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  className="bg-muted/50 border-border/40"
                />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">Tools (comma-separated)</Label>
                <Input
                  value={tools}
                  onChange={(e) => setTools(e.target.value)}
                  placeholder="web_search, read_page"
                  className="bg-muted/50 border-border/40"
                />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">System Prompt</Label>
                <textarea
                  value={systemPrompt}
                  onChange={(e) => setSystemPrompt(e.target.value)}
                  rows={8}
                  className="w-full rounded-md border border-border/40 bg-muted/50 px-3 py-2 text-sm resize-y focus:outline-none focus:ring-1 focus:ring-ring"
                />
              </div>
              <div className="flex gap-2">
                <Button size="sm" onClick={handleSave} disabled={saving}>
                  {saving ? 'Saving...' : 'Save'}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
                  Cancel
                </Button>
              </div>
            </>
          ) : (
            <>
              <p className="text-sm text-muted-foreground">{skill.description}</p>
              {skill.tools.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {skill.tools.map((t) => (
                    <span
                      key={t}
                      className="text-xs px-2 py-0.5 rounded bg-muted text-muted-foreground"
                    >
                      {t}
                    </span>
                  ))}
                </div>
              )}
              <div className="rounded-md bg-muted/50 p-3">
                <pre className="text-xs text-foreground whitespace-pre-wrap">{skill.system_prompt}</pre>
              </div>
              <div className="flex gap-2">
                {!skill.builtin && (
                  <>
                    <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
                      Edit
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="text-red-500 hover:text-red-600"
                      onClick={handleDelete}
                      disabled={deleting}
                    >
                      <Trash2 className="h-3 w-3 mr-1" />
                      {deleting ? 'Deleting...' : 'Delete'}
                    </Button>
                  </>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}

export default function SkillsTab({ active }: { active?: boolean }) {
  const [skills, setSkills] = useState<Skill[]>([])
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDescription, setNewDescription] = useState('')
  const [newTools, setNewTools] = useState('')
  const [newPrompt, setNewPrompt] = useState('')
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    try {
      const data = await get<{ skills: Skill[] }>('/api/skills')
      setSkills(data.skills)
    } catch {
      toast.error('Failed to load skills')
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => { if (active) load() }, [active])

  async function handleCreate() {
    if (!newName.trim() || !newPrompt.trim()) {
      toast.error('Name and system prompt are required')
      return
    }
    setSaving(true)
    try {
      await post('/api/skills', {
        name: newName.trim(),
        description: newDescription.trim(),
        system_prompt: newPrompt.trim(),
        tools: newTools
          .split(',')
          .map((t) => t.trim())
          .filter(Boolean),
      })
      toast.success(`Skill "${newName}" created`)
      setCreating(false)
      setNewName('')
      setNewDescription('')
      setNewTools('')
      setNewPrompt('')
      load()
    } catch {
      toast.error('Failed to create skill')
    } finally {
      setSaving(false)
    }
  }

  const builtin = skills.filter((s) => s.builtin)
  const custom = skills.filter((s) => !s.builtin)

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 py-4 sm:py-6 space-y-5">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Skills are reusable instruction sets that guide the agent for specific task types.
        </p>
        <Button size="sm" onClick={() => setCreating(!creating)}>
          <Plus className="h-4 w-4 mr-1" />
          New Skill
        </Button>
      </div>

      {creating && (
        <div className="rounded-lg border border-border/40 bg-card p-4 space-y-3">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Name</Label>
              <Input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="my-skill"
                className="bg-muted/50 border-border/40"
              />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Tools (comma-separated)</Label>
              <Input
                value={newTools}
                onChange={(e) => setNewTools(e.target.value)}
                placeholder="web_search, read_page"
                className="bg-muted/50 border-border/40"
              />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">Description</Label>
            <Input
              value={newDescription}
              onChange={(e) => setNewDescription(e.target.value)}
              placeholder="What this skill does"
              className="bg-muted/50 border-border/40"
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">System Prompt</Label>
            <textarea
              value={newPrompt}
              onChange={(e) => setNewPrompt(e.target.value)}
              rows={6}
              placeholder="Instructions for the agent when this skill is active..."
              className="w-full rounded-md border border-border/40 bg-muted/50 px-3 py-2 text-sm resize-y focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </div>
          <div className="flex gap-2">
            <Button size="sm" onClick={handleCreate} disabled={saving}>
              {saving ? 'Creating...' : 'Create Skill'}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setCreating(false)}>
              Cancel
            </Button>
          </div>
        </div>
      )}

      {custom.length > 0 && (
        <div className="space-y-3">
          <h2 className="text-sm font-medium text-muted-foreground">Custom Skills</h2>
          <div className="space-y-2">
            {custom.map((s) => (
              <SkillCard key={s.name} skill={s} onSaved={load} onDeleted={load} />
            ))}
          </div>
        </div>
      )}

      {builtin.length > 0 && (
        <div className="space-y-3">
          <h2 className="text-sm font-medium text-muted-foreground">Built-in Skills</h2>
          <div className="space-y-2">
            {builtin.map((s) => (
              <SkillCard key={s.name} skill={s} onSaved={load} onDeleted={load} />
            ))}
          </div>
        </div>
      )}

      {skills.length === 0 && (
        <p className="text-sm text-muted-foreground text-center py-8">No skills found.</p>
      )}

      <div className="h-4" />
    </div>
  )
}
