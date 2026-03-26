import { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { get } from '@/lib/api'
import { Markdown } from '@/components/ui/markdown'
import { Loader2, BookOpen } from 'lucide-react'

interface NotebookEntry {
  id: string
  content: string
  created_at: string
}

interface SharedNotebook {
  title: string
  agent_name: string
  entries: NotebookEntry[]
}

export default function SharedNotebookPage() {
  const { token } = useParams<{ token: string }>()
  const [data, setData] = useState<SharedNotebook | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    get<SharedNotebook>(`/shared/notebook/${token}`)
      .then(setData)
      .catch(() => setError('This shared notebook is no longer available.'))
      .finally(() => setLoading(false))
  }, [token])

  if (loading) {
    return (
      <div className="min-h-screen bg-background flex flex-col items-center justify-center p-6">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground mb-4" />
        <p className="text-sm text-muted-foreground animate-pulse">Loading shared notebook...</p>
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="min-h-screen bg-background flex flex-col items-center justify-center p-6 text-center">
        <div className="h-16 w-16 bg-muted rounded-full flex items-center justify-center mb-6">
          <BookOpen className="h-8 w-8 text-muted-foreground" />
        </div>
        <h1 className="text-xl font-bold mb-2">Notebook Not Found</h1>
        <p className="text-muted-foreground max-w-sm">{error || 'Invalid share link.'}</p>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b border-border/40 bg-background/50 backdrop-blur-md sticky top-0 z-10">
        <div className="max-w-3xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="h-8 w-8 bg-primary/10 rounded-lg flex items-center justify-center">
              <BookOpen className="h-4 w-4 text-primary" />
            </div>
            <div>
              <h1 className="text-sm font-bold truncate max-w-[200px] sm:max-w-md">{data.title}</h1>
              <p className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold">Shared by {data.agent_name}</p>
            </div>
          </div>
          <div className="text-[10px] bg-muted px-2 py-0.5 rounded-full font-bold uppercase tracking-widest text-muted-foreground">Read Only</div>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-12">
        <div className="space-y-12">
          {data.entries.length === 0 ? (
            <p className="text-center text-muted-foreground py-12 italic">This notebook has no entries.</p>
          ) : (
            data.entries.map((entry) => (
              <article key={entry.id} className="space-y-4">
                <div className="flex items-center gap-2 text-xs text-muted-foreground font-medium">
                  <div className="h-1.5 w-1.5 rounded-full bg-primary/40" />
                  {new Date(entry.created_at + 'Z').toLocaleString(undefined, {
                    month: 'long', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit'
                  })}
                </div>
                <div className="prose dark:prose-invert max-w-none prose-p:leading-relaxed prose-pre:bg-muted/50 prose-pre:border prose-pre:border-border/40">
                  <Markdown>{entry.content}</Markdown>
                </div>
              </article>
            ))
          )}
        </div>
      </main>

      <footer className="max-w-3xl mx-auto px-6 py-12 border-t border-border/20 text-center">
        <p className="text-xs text-muted-foreground">
          Powered by <span className="font-bold text-foreground/80">Odigos</span> — Self-Hosted Personal AI
        </p>
      </footer>
    </div>
  )
}
