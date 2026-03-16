import { useState, useEffect, useCallback } from 'react'
import { get, del } from '@/lib/api'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { FileText, Trash2, AlertTriangle } from 'lucide-react'

interface Document {
  id: string
  filename: string
  file_size: number | null
  chunk_count: number | null
  status: string
  ingested_at: string | null
}

interface DocumentsResponse {
  documents: Document[]
  summary: {
    total_documents: number
    total_chunks: number
    estimated_size_mb: number
  }
  storage_warning: boolean
}

function formatSize(bytes: number | null): string {
  if (!bytes) return '--'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(iso: string | null): string {
  if (!iso) return '--'
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    })
  } catch {
    return iso
  }
}

function DocumentCard({
  doc,
  onDeleted,
}: {
  doc: Document
  onDeleted: () => void
}) {
  const [deleting, setDeleting] = useState(false)

  async function handleDelete() {
    setDeleting(true)
    try {
      await del(`/api/documents/${doc.id}`)
      toast.success(`Deleted "${doc.filename}"`)
      onDeleted()
    } catch {
      toast.error('Failed to delete document')
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="rounded-lg border border-border/40 bg-card px-4 py-3 flex items-center justify-between gap-3">
      <div className="flex items-center gap-3 min-w-0">
        <FileText className="h-4 w-4 text-muted-foreground shrink-0" />
        <div className="min-w-0">
          <p className="text-sm font-medium truncate">{doc.filename}</p>
          <p className="text-xs text-muted-foreground">
            {formatSize(doc.file_size)}
            {' / '}
            {doc.chunk_count ?? 0} chunks
            {' / '}
            {formatDate(doc.ingested_at)}
            {doc.status && doc.status !== 'ingested' && (
              <span className="ml-2 text-yellow-500">{doc.status}</span>
            )}
          </p>
        </div>
      </div>
      <Button
        size="sm"
        variant="ghost"
        onClick={handleDelete}
        disabled={deleting}
        className="text-muted-foreground hover:text-destructive shrink-0"
      >
        <Trash2 className="h-3.5 w-3.5" />
      </Button>
    </div>
  )
}

export default function DocumentsTab({ active }: { active?: boolean }) {
  const [data, setData] = useState<DocumentsResponse | null>(null)

  const load = useCallback(async () => {
    try {
      const res = await get<DocumentsResponse>('/api/documents')
      setData(res)
    } catch {
      toast.error('Failed to load documents')
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    if (active) load()
  }, [active, load])

  const summary = data?.summary
  const documents = data?.documents ?? []

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 py-4 sm:py-6 space-y-5">
      <p className="text-sm text-muted-foreground">
        Documents uploaded and ingested into the agent's memory. Each document
        is chunked and embedded for retrieval during conversations.
      </p>

      {summary && (
        <div className="flex gap-4 text-sm">
          <div className="rounded-md bg-muted/50 px-3 py-2">
            <span className="text-muted-foreground">Documents:</span>{' '}
            <span className="font-medium">{summary.total_documents}</span>
          </div>
          <div className="rounded-md bg-muted/50 px-3 py-2">
            <span className="text-muted-foreground">Chunks:</span>{' '}
            <span className="font-medium">{summary.total_chunks.toLocaleString()}</span>
          </div>
          <div className="rounded-md bg-muted/50 px-3 py-2">
            <span className="text-muted-foreground">Size:</span>{' '}
            <span className="font-medium">{summary.estimated_size_mb} MB</span>
          </div>
        </div>
      )}

      {data?.storage_warning && (
        <div className="flex items-center gap-2 rounded-md border border-yellow-500/40 bg-yellow-500/10 px-4 py-3 text-sm text-yellow-600 dark:text-yellow-400">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span>
            Storage is near capacity (over 200K chunks). Consider deleting
            unused documents to free space.
          </span>
        </div>
      )}

      {documents.length > 0 && (
        <div className="space-y-2">
          {documents.map((doc) => (
            <DocumentCard key={doc.id} doc={doc} onDeleted={load} />
          ))}
        </div>
      )}

      {data && documents.length === 0 && (
        <p className="text-sm text-muted-foreground text-center py-8">
          No documents uploaded yet. Upload files through the chat or API.
        </p>
      )}

      <div className="h-4" />
    </div>
  )
}
