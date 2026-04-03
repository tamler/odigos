import { useState, useRef, useCallback } from 'react'
import { ChevronRight } from 'lucide-react'

interface NotebookItem {
  id: string
  title: string
  mode?: string
  updated_at: string
}

interface Props {
  notebooks: NotebookItem[]
  currentPath: string
  onNavigate: (path: string) => void
}

const STORAGE_KEY_COLLAPSED = 'odigos-nb-collapsed'
const STORAGE_KEY_ORDER = 'odigos-nb-mode-order'

function loadSet(key: string): Set<string> {
  try { return new Set(JSON.parse(localStorage.getItem(key) || '[]')) } catch { return new Set() }
}

function loadArray(key: string): string[] {
  try { return JSON.parse(localStorage.getItem(key) || '[]') } catch { return [] }
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1)
}

export function NotebookSidebar({ notebooks, currentPath, onNavigate }: Props) {
  const [collapsed, setCollapsed] = useState<Set<string>>(() => loadSet(STORAGE_KEY_COLLAPSED))
  const [modeOrder, setModeOrder] = useState<string[]>(() => loadArray(STORAGE_KEY_ORDER))
  const dragMode = useRef<string | null>(null)

  // Group notebooks by mode
  const grouped: Record<string, NotebookItem[]> = {}
  for (const nb of notebooks) {
    const mode = nb.mode || 'general'
    ;(grouped[mode] ||= []).push(nb)
  }

  // Sort modes: saved order first, then remaining alphabetically
  const allModes = Object.keys(grouped)
  const ordered = [
    ...modeOrder.filter(m => allModes.includes(m)),
    ...allModes.filter(m => !modeOrder.includes(m)).sort(),
  ]

  const toggleCollapse = useCallback((mode: string) => {
    setCollapsed(prev => {
      const next = new Set(prev)
      if (next.has(mode)) next.delete(mode)
      else next.add(mode)
      localStorage.setItem(STORAGE_KEY_COLLAPSED, JSON.stringify([...next]))
      return next
    })
  }, [])

  const persistOrder = useCallback((newOrder: string[]) => {
    setModeOrder(newOrder)
    localStorage.setItem(STORAGE_KEY_ORDER, JSON.stringify(newOrder))
  }, [])

  const handleDragStart = (mode: string) => { dragMode.current = mode }

  const handleDragOver = (e: React.DragEvent) => { e.preventDefault() }

  const handleDrop = (targetMode: string) => {
    const src = dragMode.current
    if (!src || src === targetMode) return
    const current = [...ordered]
    const srcIdx = current.indexOf(src)
    const targetIdx = current.indexOf(targetMode)
    if (srcIdx === -1 || targetIdx === -1) return
    current.splice(srcIdx, 1)
    current.splice(targetIdx, 0, src)
    persistOrder(current)
    dragMode.current = null
  }

  return (
    <div className="space-y-1">
      {ordered.map(mode => {
        const nbs = grouped[mode]
        if (!nbs?.length) return null
        const isCollapsed = collapsed.has(mode)
        return (
          <div key={mode}>
            <button
              draggable
              onDragStart={() => handleDragStart(mode)}
              onDragOver={handleDragOver}
              onDrop={() => handleDrop(mode)}
              onClick={() => toggleCollapse(mode)}
              className="w-full flex items-center gap-1.5 px-3 py-1.5 group cursor-grab active:cursor-grabbing"
            >
              <ChevronRight className={`h-3 w-3 text-muted-foreground/50 transition-transform duration-150 ${isCollapsed ? '' : 'rotate-90'}`} />
              <span className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground/60 group-hover:text-muted-foreground transition-colors">
                {capitalize(mode)}
              </span>
              <span className="ml-auto text-[10px] text-muted-foreground/40">{nbs.length}</span>
            </button>
            {!isCollapsed && (
              <div className="space-y-0.5 ml-1">
                {nbs.map(nb => (
                  <button
                    key={nb.id}
                    onClick={() => onNavigate(`/notebooks/${nb.id}`)}
                    className={`w-full text-left px-3 py-2 rounded-lg text-sm truncate transition-colors ${
                      currentPath.includes(nb.id)
                        ? 'bg-primary/10 text-primary font-bold shadow-sm'
                        : 'text-muted-foreground hover:bg-accent/50'
                    }`}
                  >
                    {nb.title}
                  </button>
                ))}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
