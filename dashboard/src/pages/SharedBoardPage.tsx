import { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { get } from '@/lib/api'
import { Loader2, Columns3 } from 'lucide-react'

interface Column {
  id: string
  title: string
  position: number
}

interface Card {
  id: string
  column_id: string
  title: string
  body: string | null
  position: number
}

interface SharedBoard {
  title: string
  agent_name: string
  columns: Column[]
  cards: Card[]
}

export default function SharedBoardPage() {
  const { token } = useParams<{ token: string }>()
  const [data, setData] = useState<SharedBoard | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    get<SharedBoard>(`/shared/board/${token}`)
      .then(setData)
      .catch(() => setError('This shared board is no longer available.'))
      .finally(() => setLoading(false))
  }, [token])

  if (loading) {
    return (
      <div className="min-h-screen bg-background flex flex-col items-center justify-center p-6">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground mb-4" />
        <p className="text-sm text-muted-foreground animate-pulse">Loading shared board...</p>
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="min-h-screen bg-background flex flex-col items-center justify-center p-6 text-center">
        <div className="h-16 w-16 bg-muted rounded-full flex items-center justify-center mb-6">
          <Columns3 className="h-8 w-8 text-muted-foreground" />
        </div>
        <h1 className="text-xl font-bold mb-2">Board Not Found</h1>
        <p className="text-muted-foreground max-w-sm">{error || 'Invalid share link.'}</p>
      </div>
    )
  }

  const sortedColumns = [...data.columns].sort((a, b) => a.position - b.position)
  const cardsByColumn: Record<string, Card[]> = {}
  for (const col of data.columns) cardsByColumn[col.id] = []
  for (const card of data.cards) {
    if (cardsByColumn[card.column_id]) cardsByColumn[card.column_id].push(card)
  }
  for (const colId of Object.keys(cardsByColumn)) {
    cardsByColumn[colId].sort((a, b) => a.position - b.position)
  }

  return (
    <div className="min-h-screen bg-muted/30 flex flex-col overflow-hidden">
      <header className="border-b border-border/40 bg-background/50 backdrop-blur-md shrink-0">
        <div className="px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="h-8 w-8 bg-primary/10 rounded-lg flex items-center justify-center">
              <Columns3 className="h-4 w-4 text-primary" />
            </div>
            <div>
              <h1 className="text-sm font-bold truncate max-w-[200px] sm:max-w-md">{data.title}</h1>
              <p className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold">Shared by {data.agent_name}</p>
            </div>
          </div>
          <div className="text-[10px] bg-background border border-border/60 px-2 py-0.5 rounded-full font-bold uppercase tracking-widest text-muted-foreground shadow-sm">Read Only</div>
        </div>
      </header>

      <main className="flex-1 overflow-x-auto px-6 py-8 touch-pan-x">
        <div className="h-full inline-flex gap-4 items-start">
          {sortedColumns.map((col) => {
            const cards = cardsByColumn[col.id] ?? []
            return (
              <div key={col.id} className="w-72 flex flex-col max-h-full rounded-xl border border-border/40 bg-background/60 shadow-sm overflow-hidden">
                <div className="px-4 py-3 flex items-center justify-between border-b border-border/20">
                  <h3 className="text-sm font-bold truncate pr-2">{col.title}</h3>
                  <span className="text-[10px] font-bold bg-muted px-1.5 py-0.5 rounded text-muted-foreground">{cards.length}</span>
                </div>
                <div className="flex-1 overflow-y-auto p-2 space-y-2">
                  {cards.map((card) => (
                    <div key={card.id} className="p-3 rounded-lg border border-border/20 bg-background shadow-sm space-y-2">
                      <h4 className="text-sm font-semibold leading-tight">{card.title}</h4>
                      {card.body && (
                        <p className="text-xs text-muted-foreground leading-relaxed whitespace-pre-wrap">{card.body}</p>
                      )}
                    </div>
                  ))}
                  {cards.length === 0 && (
                    <div className="py-8 text-center">
                      <p className="text-[10px] text-muted-foreground italic uppercase tracking-wider">No cards</p>
                    </div>
                  )}
                </div>
              </div>
            )
          })}
          <div className="w-12 shrink-0" />
        </div>
      </main>

      <footer className="px-6 py-4 bg-background/50 border-t border-border/20 text-center shrink-0">
        <p className="text-[10px] text-muted-foreground uppercase tracking-[0.2em] font-semibold">
          Powered by <span className="text-foreground">Odigos</span>
        </p>
      </footer>
    </div>
  )
}
