import { useState, useEffect, useCallback, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { get, post, del } from '@/lib/api'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Plus, ArrowLeft, Trash2 } from 'lucide-react'
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
  return <BoardList />
}

function BoardList() {
  const navigate = useNavigate()
  const [boards, setBoards] = useState<Board[]>([])
  const [loading, setLoading] = useState(true)
  const [newTitle, setNewTitle] = useState('')
  const [creating, setCreating] = useState(false)

  const loadBoards = useCallback(() => {
    setLoading(true)
    get<{ boards: Board[] }>('/api/kanban/boards')
      .then((data) => setBoards(data.boards))
      .catch(() => toast.error('Failed to load boards'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { loadBoards() }, [loadBoards])

  async function handleCreate() {
    const title = newTitle.trim()
    if (!title) return
    setCreating(true)
    try {
      const board = await post<Board>('/api/kanban/boards', { title })
      setNewTitle('')
      navigate(`/kanban/${board.id}`)
    } catch {
      toast.error('Failed to create board')
    } finally {
      setCreating(false)
    }
  }

  async function handleDelete(id: string, e: React.MouseEvent) {
    e.stopPropagation()
    try {
      await del(`/api/kanban/boards/${id}`)
      setBoards((prev) => prev.filter((b) => b.id !== id))
      toast.success('Board deleted')
    } catch {
      toast.error('Failed to delete board')
    }
  }

  return (
    <div className="flex flex-col h-full max-w-2xl mx-auto w-full px-4 py-8">
      <h1 className="text-2xl font-semibold mb-6">Kanban Boards</h1>

      <div className="flex gap-2 mb-6">
        <Input
          value={newTitle}
          onChange={(e) => setNewTitle(e.target.value)}
          placeholder="New board title..."
          onKeyDown={(e) => { if (e.key === 'Enter') handleCreate() }}
          className="flex-1"
        />
        <Button onClick={handleCreate} disabled={creating || !newTitle.trim()}>
          <Plus className="h-4 w-4 mr-1" /> Create
        </Button>
      </div>

      {loading ? (
        <div className="text-muted-foreground text-sm">Loading...</div>
      ) : boards.length === 0 ? (
        <div className="text-muted-foreground text-sm">No boards yet. Create one above.</div>
      ) : (
        <div className="space-y-2">
          {boards.map((b) => (
            <div
              key={b.id}
              onClick={() => navigate(`/kanban/${b.id}`)}
              className="flex items-center justify-between px-4 py-3 rounded-md border border-border/50 hover:bg-accent/50 cursor-pointer transition-colors group"
            >
              <div>
                <div className="text-sm font-medium">{b.title}</div>
                <div className="text-xs text-muted-foreground mt-0.5">
                  {new Date(b.updated_at + 'Z').toLocaleDateString(undefined, {
                    month: 'short', day: 'numeric', year: 'numeric',
                  })}
                </div>
              </div>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-destructive"
                onClick={(e) => handleDelete(b.id, e)}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function BoardDetailInner({ boardId, board, setBoard }: {
  boardId: string
  board: BoardDetail
  setBoard: React.Dispatch<React.SetStateAction<BoardDetail | null>>
}) {
  const navigate = useNavigate()
  const [newCardTexts, setNewCardTexts] = useState<Record<string, string>>({})
  const [newColumnTitle, setNewColumnTitle] = useState('')
  const [addingColumn, setAddingColumn] = useState(false)
  const { onDragEnd } = useDndEvents()

  // Group cards by column_id, sorted by position
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

  const sortedColumns = [...board.columns].sort((a, b) => a.position - b.position)

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-border/40 shrink-0">
        <Button variant="ghost" size="icon" onClick={() => navigate('/kanban')} className="shrink-0">
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <h1 className="text-base font-semibold truncate">{board.title}</h1>
      </div>

      {/* Board */}
      <div className="flex-1 overflow-hidden px-4 py-4">
        <KanbanBoard>
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
          <div className="w-64 flex-shrink-0">
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

          <KanbanBoardExtraMargin />
        </KanbanBoard>
      </div>
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
      <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
        Loading...
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
