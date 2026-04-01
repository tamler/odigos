import { useState, useEffect, useCallback, useMemo } from 'react'
import { useParams, useNavigate, useOutletContext } from 'react-router-dom'
import { get, post, del, patch } from '@/lib/api'
import { useUIStore } from '@/stores/uiStore'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Plus, Trash2, Share2, Globe, Maximize2, Minimize2 } from 'lucide-react'
import { ShareDialog } from '@/components/ShareDialog'
import { AgentInputBar } from '@/components/AgentInputBar'
import {
  KanbanBoardProvider,
  KanbanBoard,
  KanbanBoardColumn,
  KanbanBoardColumnHeader,
  KanbanBoardColumnTitle,
  KanbanBoardColumnList,
  KanbanBoardColumnListItem,
  KanbanBoardCard,
  KanbanBoardCardTitle,
  KanbanBoardCardButtonGroup,
  KanbanBoardCardButton,
  KanbanBoardColumnFooter,
  KanbanBoardColumnButton,
  KanbanBoardExtraMargin,
} from '@/components/kanban'
import { useDndEvents } from '@/components/kanban'

interface Board {
  id: string
  title: string
  share_token?: string | null
  created_at: string
  updated_at: string
}

interface Column {
  id: string
  board_id: string
  title: string
  position: number
}

interface Card {
  id: string
  board_id: string
  column_id: string
  title: string
  body: string | null
  position: number
  created_at: string
}

interface BoardDetail extends Board {
  columns: Column[]
  cards: Card[]
}

export default function KanbanPage() {
  const { id } = useParams<{ id?: string }>()

  if (id) {
    return <BoardDetail boardId={id} />
  }
  return <KanbanAutoRedirect />
}

function KanbanAutoRedirect() {
  const navigate = useNavigate()
  useEffect(() => {
    get<{ boards: Board[] }>('/api/kanban/boards')
      .then((data) => {
        if (data.boards.length === 0) {
          post<Board>('/api/kanban/boards', { title: 'My Board' })
            .then(b => navigate(`/kanban/${b.id}`, { replace: true }))
        } else {
          const latest = data.boards.sort((a,b) => new Date(b.updated_at + 'Z').getTime() - new Date(a.updated_at + 'Z').getTime())[0]
          navigate(`/kanban/${latest.id}`, { replace: true })
        }
      })
      .catch(() => {})
  }, [navigate])
  return <div className="p-8 text-sm text-muted-foreground animate-pulse">Loading board...</div>
}



function BoardDetailInner({ boardId, board, setBoard }: {
  boardId: string
  board: BoardDetail
  setBoard: React.Dispatch<React.SetStateAction<BoardDetail | null>>
}) {
  const navigate = useNavigate()
  let outletCtx: any = {}
  try { outletCtx = useOutletContext<any>() || {} } catch { outletCtx = {} }
  const { setPageContextData = () => {}, socketRef } = outletCtx
  const isMobile = useUIStore(s => s.isMobile)
  const connected = useUIStore(s => s.connected)
  const agentName = useUIStore(s => s.agentName)
  const focusMode = useUIStore(s => s.focusMode)
  const setFocusMode = useUIStore(s => s.setFocusMode)
  const sttAvailable = true
  const [newCardTexts, setNewCardTexts] = useState<Record<string, string>>({})
  const [newColumnTitle, setNewColumnTitle] = useState('')
  const [addingColumn, setAddingColumn] = useState(false)
  const [shareOpen, setShareOpen] = useState(false)
  const [title, setTitle] = useState(board.title)
  const { onDragEnd } = useDndEvents()

  useEffect(() => {
    setTitle(board.title)
  }, [board.title])

  // Focus mode keyboard shortcut (G-W5)
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === '.') {
        e.preventDefault()
        setFocusMode(!useUIStore.getState().focusMode)
      }
      if (e.key === 'Escape' && focusMode) {
        setFocusMode(false)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [focusMode, setFocusMode])

  const handleUpdateTitle = async () => {
    if (title === board.title || !title.trim()) return
    try {
      await patch(`/api/kanban/boards/${boardId}`, { title: title.trim() })
      setBoard({ ...board, title: title.trim() })
      toast.success('Title updated')
    } catch {
      toast.error('Failed to update title')
      setTitle(board.title)
    }
  }

  const cardsByColumn = useMemo(() => {
    const map: Record<string, Card[]> = {}
    for (const col of board.columns) {
      map[col.id] = []
    }
    for (const card of board.cards) {
      if (!map[card.column_id]) map[card.column_id] = []
      map[card.column_id].push(card)
    }
    for (const colId of Object.keys(map)) {
      map[colId].sort((a, b) => a.position - b.position)
    }
    return map
  }, [board.columns, board.cards])

  // Build a map from cardId -> columnId for fast lookup
  const cardColumnMap = useMemo(() => {
    const map: Record<string, string> = {}
    for (const card of board.cards) {
      map[card.id] = card.column_id
    }
    return map
  }, [board.cards])

  async function handleMoveCard(cardId: string, targetId: string) {
    // targetId could be a column id or a card id (drop onto card -> same column)
    let targetColumnId: string
    if (cardsByColumn[targetId] !== undefined) {
      // targetId is a column
      targetColumnId = targetId
    } else if (cardColumnMap[targetId] !== undefined) {
      // targetId is a card — move to its column
      targetColumnId = cardColumnMap[targetId]
    } else {
      return
    }

    // Optimistically update UI
    setBoard((prev) => {
      if (!prev) return prev
      const updatedCards = prev.cards.map((c) =>
        c.id === cardId ? { ...c, column_id: targetColumnId } : c
      )
      return { ...prev, cards: updatedCards }
    })

    try {
      await post(`/api/kanban/boards/${boardId}/cards/${cardId}/move`, {
        column_id: targetColumnId,
        position: 0,
      })
    } catch {
      toast.error('Failed to move card')
      // Revert by reloading
      get<BoardDetail>(`/api/kanban/boards/${boardId}`)
        .then((data) => setBoard(data))
        .catch(() => {})
    }
  }

  async function handleAddCard(columnId: string) {
    const title = (newCardTexts[columnId] || '').trim()
    if (!title) return
    try {
      const card = await post<Card>(`/api/kanban/boards/${boardId}/cards`, {
        column_id: columnId,
        title,
        position: (cardsByColumn[columnId]?.length ?? 0),
      })
      setBoard((prev) => prev ? { ...prev, cards: [...prev.cards, card] } : prev)
      setNewCardTexts((prev) => ({ ...prev, [columnId]: '' }))
    } catch {
      toast.error('Failed to add card')
    }
  }

  async function handleDeleteCard(cardId: string) {
    try {
      await del(`/api/kanban/boards/${boardId}/cards/${cardId}`)
      setBoard((prev) => prev ? { ...prev, cards: prev.cards.filter((c) => c.id !== cardId) } : prev)
    } catch {
      toast.error('Failed to delete card')
    }
  }

  async function handleAddColumn() {
    const title = newColumnTitle.trim()
    if (!title) return
    setAddingColumn(true)
    try {
      const col = await post<Column>(`/api/kanban/boards/${boardId}/columns`, {
        title,
        position: board.columns.length,
      })
      setBoard((prev) => prev ? { ...prev, columns: [...prev.columns, col] } : prev)
      setNewColumnTitle('')
    } catch {
      toast.error('Failed to add column')
    } finally {
      setAddingColumn(false)
    }
  }

  async function handleDeleteColumn(columnId: string) {
    try {
      await del(`/api/kanban/boards/${boardId}/columns/${columnId}`)
      setBoard((prev) => {
        if (!prev) return prev
        return {
          ...prev,
          columns: prev.columns.filter((c) => c.id !== columnId),
          cards: prev.cards.filter((c) => c.column_id !== columnId),
        }
      })
    } catch {
      toast.error('Failed to delete column')
    }
  }

  useEffect(() => {
    if (board) {
      setPageContextData({
        page_id: boardId,
        page_title: board.title,
      })
    }
    return () => setPageContextData({})
  }, [boardId, board?.title, setPageContextData])

  const sortedColumns = [...board.columns].sort((a, b) => a.position - b.position)

  return (
    <div className={`flex-1 flex flex-col h-full bg-background transition-[padding,inset] duration-300 ${focusMode ? 'fixed inset-0 z-[100] p-4 sm:p-12 overflow-y-auto' : 'overflow-hidden'}`}>
      {/* Header */}
      {!focusMode && (
        <div className="flex items-center justify-between px-6 py-4 pl-14 lg:pl-6 border-b border-border/40 shrink-0 bg-background/50 backdrop-blur-sm sticky top-0 z-20">
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onBlur={handleUpdateTitle}
            onKeyDown={(e) => e.key === 'Enter' && handleUpdateTitle()}
            className="text-xl font-bold bg-transparent border-none focus:outline-none w-full max-w-md tracking-tight placeholder:text-muted-foreground/50"
            placeholder="Untitled board"
          />
          
          <div className="flex items-center gap-2">
            <Button 
              variant="ghost" 
              size="icon" 
              className="h-9 w-9 text-muted-foreground" 
              onClick={() => setFocusMode(true)}
              title="Focus Mode (Cmd+.)"
            >
              <Maximize2 className="h-4 w-4" />
            </Button>
            <Button 
              variant="ghost" 
              size="icon" 
              className={`h-9 w-9 ${board.share_token ? 'text-primary' : 'text-muted-foreground'}`}
              onClick={() => setShareOpen(true)}
              title="Share board"
            >
              {board.share_token ? <Globe className="h-4 w-4" /> : <Share2 className="h-4 w-4" />}
            </Button>
            <Button variant="ghost" size="icon" className="h-9 w-9 text-muted-foreground hover:text-destructive" onClick={async () => {
               if (confirm('Delete this entire board?')) {
                 await del(`/api/kanban/boards/${boardId}`)
                 navigate('/kanban')
               }
            }}>
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        </div>
      )}

      {/* Board */}
      <div className={`flex-1 overflow-y-auto lg:overflow-hidden px-4 py-4 scrollbar-hide ${focusMode ? 'max-w-6xl mx-auto w-full' : ''}`}>
        <KanbanBoard className={isMobile ? "flex-col gap-8 pb-20" : "flex-row"}>
          {sortedColumns.map((col) => {
            const cards = cardsByColumn[col.id] ?? []
            return (
              <KanbanBoardColumn
                key={col.id}
                columnId={col.id}
                onDropOverColumn={(data) => {
                  try {
                    const parsed = JSON.parse(data) as { id: string }
                    handleMoveCard(parsed.id, col.id)
                    onDragEnd(parsed.id, col.id)
                  } catch {
                    // ignore
                  }
                }}
              >
                <KanbanBoardColumnHeader>
                  <KanbanBoardColumnTitle columnId={col.id}>
                    {col.title}
                    <span className="ml-2 text-xs text-muted-foreground/60">{cards.length}</span>
                  </KanbanBoardColumnTitle>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label="Delete column"
                    className="h-6 w-6 text-muted-foreground hover:text-destructive"
                    onClick={() => handleDeleteColumn(col.id)}
                  >
                    <Trash2 className="h-3 w-3" />
                  </Button>
                </KanbanBoardColumnHeader>

                <KanbanBoardColumnList>
                  {cards.map((card) => (
                    <KanbanBoardColumnListItem
                      key={card.id}
                      cardId={card.id}
                      onDropOverListItem={(data) => {
                        try {
                          const parsed = JSON.parse(data) as { id: string }
                          handleMoveCard(parsed.id, card.id)
                        } catch {
                          // ignore
                        }
                      }}
                    >
                      <KanbanBoardCard data={{ id: card.id }}>
                        <KanbanBoardCardTitle>{card.title}</KanbanBoardCardTitle>
                        {card.body && (
                          <p className="text-xs text-muted-foreground leading-5 whitespace-pre-wrap">{card.body}</p>
                        )}
                        <KanbanBoardCardButtonGroup>
                          <KanbanBoardCardButton
                            tooltip="Delete"
                            onClick={() => handleDeleteCard(card.id)}
                          >
                            <Trash2 />
                          </KanbanBoardCardButton>
                        </KanbanBoardCardButtonGroup>
                      </KanbanBoardCard>
                    </KanbanBoardColumnListItem>
                  ))}
                </KanbanBoardColumnList>

                <KanbanBoardColumnFooter>
                  <div className="flex w-full gap-1">
                    <Input
                      value={newCardTexts[col.id] ?? ''}
                      onChange={(e) => setNewCardTexts((prev) => ({ ...prev, [col.id]: e.target.value }))}
                      placeholder="Add card..."
                      className="h-7 text-xs flex-1"
                      onKeyDown={(e) => { if (e.key === 'Enter') handleAddCard(col.id) }}
                    />
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label="Add card"
                      className="h-7 w-7 shrink-0"
                      onClick={() => handleAddCard(col.id)}
                      disabled={!(newCardTexts[col.id] || '').trim()}
                    >
                      <Plus className="h-3 w-3" />
                    </Button>
                  </div>
                </KanbanBoardColumnFooter>
              </KanbanBoardColumn>
            )
          })}

          {/* Add column */}
          <div className={`${isMobile ? 'w-full' : 'w-64'} flex-shrink-0 pb-12 sm:pb-0`}>
            <div className="flex gap-1">
              <Input
                value={newColumnTitle}
                onChange={(e) => setNewColumnTitle(e.target.value)}
                placeholder="New column..."
                className="h-8 text-sm"
                onKeyDown={(e) => { if (e.key === 'Enter') handleAddColumn() }}
              />
              <KanbanBoardColumnButton
                onClick={handleAddColumn}
                disabled={addingColumn || !newColumnTitle.trim()}
                className="w-auto px-2 shrink-0"
              >
                <Plus className="h-4 w-4" />
              </KanbanBoardColumnButton>
            </div>
          </div>

          {!isMobile && <KanbanBoardExtraMargin />}
        </KanbanBoard>
      </div>

      {/* Agent Input Bar (G-W3) */}
      {!focusMode && (
        <div className="bg-gradient-to-t from-background via-background/90 to-transparent pt-12 pb-4 pointer-events-none">
          <div className="pointer-events-auto">
            <AgentInputBar
              agentName={agentName}
              placeholder="Ask about this board..."
              pageContext={{
                page: 'kanban',
                page_id: boardId,
                page_title: board.title,
                visible_data: `Columns: ${board.columns.map(c => c.title).join(', ')}. ${board.cards.length} cards.`
              }}
              socketRef={socketRef}
              connected={connected}
              sttAvailable={sttAvailable}
            />
          </div>
        </div>
      )}

      {/* Focus Mode Exit */}
      {focusMode && (
        <Button 
          variant="secondary" 
          size="sm" 
          className="fixed top-6 right-6 z-[110] shadow-lg rounded-full"
          onClick={() => setFocusMode(false)}
        >
          <Minimize2 className="h-4 w-4 mr-2" />
          Exit Focus
        </Button>
      )}

      <ShareDialog
        type="board"
        id={boardId}
        isOpen={shareOpen}
        onClose={() => {
          setShareOpen(false)
          get<BoardDetail>(`/api/kanban/boards/${boardId}`)
            .then((data) => setBoard(data))
            .catch(() => {})
        }}
        initialShareToken={board?.share_token}
      />
    </div>
  )
}

function BoardDetail({ boardId }: { boardId: string }) {
  const navigate = useNavigate()
  const [board, setBoard] = useState<BoardDetail | null>(null)
  const [loading, setLoading] = useState(true)

  const loadBoard = useCallback(() => {
    setLoading(true)
    get<BoardDetail>(`/api/kanban/boards/${boardId}`)
      .then((data) => setBoard(data))
      .catch(() => {
        toast.error('Failed to load board')
        navigate('/kanban')
      })
      .finally(() => setLoading(false))
  }, [boardId, navigate])

  useEffect(() => { loadBoard() }, [loadBoard])

  if (loading) {
    return (
      <div className="flex flex-col h-full overflow-hidden px-4">
        <div className="flex items-center gap-3 py-3 border-b border-border/40 shrink-0">
          <Skeleton className="h-8 w-8 rounded-md" />
          <Skeleton className="h-6 w-48" />
        </div>
        <div className="flex-1 py-4 flex gap-4 overflow-hidden">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-full w-64 rounded-xl shrink-0" />
          ))}
        </div>
      </div>
    )
  }

  if (!board) return null

  return (
    <KanbanBoardProvider>
      <BoardDetailInner boardId={boardId} board={board} setBoard={setBoard} />
    </KanbanBoardProvider>
  )
}
