import { Download, FileText, FileSpreadsheet, FileJson, FileCode, FileImage, File } from 'lucide-react'
import { Button } from '@/components/ui/button'

export interface Artifact {
  id: string
  conversation_id?: string
  filename: string
  content_type: string
  file_size: number
  created_at: string
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function getFileIcon(contentType: string, filename: string) {
  const c = contentType.toLowerCase()
  const f = filename.toLowerCase()
  
  if (c.includes('csv') || c.includes('spreadsheet') || f.endsWith('.csv') || f.endsWith('.xlsx')) return <FileSpreadsheet className="h-5 w-5" />
  if (c.includes('json') || f.endsWith('.json')) return <FileJson className="h-5 w-5" />
  if (c.includes('javascript') || c.includes('typescript') || c.includes('html') || c.includes('code') || f.endsWith('.js') || f.endsWith('.ts') || f.endsWith('.jsx') || f.endsWith('.tsx')) return <FileCode className="h-5 w-5" />
  if (c.includes('image') || f.endsWith('.png') || f.endsWith('.jpg') || f.endsWith('.jpeg') || f.endsWith('.svg')) return <FileImage className="h-5 w-5" />
  if (c.includes('text') || c.includes('markdown') || f.endsWith('.txt') || f.endsWith('.md')) return <FileText className="h-5 w-5" />
  
  return <File className="h-5 w-5" />
}

export function ArtifactCard({ artifact, className = '' }: { artifact: Artifact, className?: string }) {
  const handleDownload = () => {
    window.open(`/api/artifacts/${artifact.id}/download`, '_blank')
  }

  return (
    <div className={`group flex items-center justify-between p-3 rounded-lg border border-border/40 bg-card hover:border-border transition-colors w-full sm:w-[320px] shadow-sm ${className}`}>
      <div className="flex items-center gap-3 overflow-hidden">
        <div className="flex items-center justify-center h-10 w-10 rounded-md bg-muted text-muted-foreground shrink-0 group-hover:bg-primary/10 group-hover:text-primary transition-colors">
          {getFileIcon(artifact.content_type, artifact.filename)}
        </div>
        <div className="overflow-hidden">
          <p className="text-sm font-medium truncate shrink-0" title={artifact.filename}>
            {artifact.filename}
          </p>
          <p className="text-xs text-muted-foreground">
            {formatFileSize(artifact.file_size)}
          </p>
        </div>
      </div>
      <Button variant="ghost" size="icon" className="shrink-0 h-8 w-8 hover:bg-muted" onClick={handleDownload} aria-label={`Download ${artifact.filename}`}>
        <Download className="h-4 w-4" />
      </Button>
    </div>
  )
}
