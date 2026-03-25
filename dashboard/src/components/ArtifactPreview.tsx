import { useState, useEffect } from 'react'
import { get, put } from '@/lib/api'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { X, ExternalLink, Download, Code, Eye, FileText, Save } from 'lucide-react'
import { ArtifactCard } from './ArtifactCard'
import { MarkdownEditor, CodeEditor } from './Editor'

  interface ArtifactContent {
    content: string
    content_type: string
    filename: string
    file_size: number
  }

interface ArtifactPreviewProps {
  artifactId: string
  onClose: () => void
}

type PreviewTab = 'preview' | 'code' | 'download'

export function ArtifactPreview({ artifactId, onClose }: ArtifactPreviewProps) {
  const [data, setData] = useState<ArtifactContent | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [activeTab, setActiveTab] = useState<PreviewTab>('preview')
  const [editContent, setEditContent] = useState('')
  const [isDirty, setIsDirty] = useState(false)

  useEffect(() => {
    let mounted = true
    setLoading(true)
    get<ArtifactContent>(`/api/artifacts/${artifactId}/content`)
      .then((res) => {
        if (mounted) {
          setData(res)
          setEditContent(res.content)
          setIsDirty(false)
          // Default to download tab if not previewable text
          const previewable = res.content_type.startsWith('text/') || 
                            res.content_type === 'application/json' ||
                            res.content_type === 'application/xml'
          if (!previewable) setActiveTab('download')
        }
      })
      .catch(() => {
        if (mounted) toast.error('Failed to load artifact content')
      })
      .finally(() => {
        if (mounted) setLoading(false)
      })
    return () => { mounted = false }
  }, [artifactId])

  async function handleSave() {
    if (!isDirty || saving) return
    setSaving(true)
    try {
      await put(`/api/artifacts/${artifactId}/content`, { content: editContent })
      toast.success('Artifact saved')
      setIsDirty(false)
      // Update local data size if possible or just rely on backend
    } catch {
      toast.error('Failed to save artifact')
    } finally {
      setSaving(false)
    }
  }

  const handleContentChange = (newContent: string) => {
    setEditContent(newContent)
    setIsDirty(true)
  }

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center h-full bg-muted/5 border-l border-border/40">
        <div className="flex flex-col items-center gap-3">
          <div className="h-6 w-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
          <p className="text-sm text-muted-foreground font-medium">Loading artifact...</p>
        </div>
      </div>
    )
  }

  if (!data) return null

  const isHtml = data.content_type === 'text/html'
  const isMarkdown = data.content_type === 'text/markdown'
  const isJson = data.content_type === 'application/json'
  const isPreviewable = isHtml || isMarkdown || data.content_type.startsWith('text/') || isJson

  return (
    <div className="flex-1 flex flex-col h-full bg-background border-l border-border/40 overflow-hidden shadow-2xl">
      {/* Header */}
      <header className="flex items-center justify-between px-4 py-3 border-b border-border/40 bg-muted/5">
        <div className="flex items-center gap-3 min-w-0">
          <div className="p-2 bg-primary/10 rounded-lg shrink-0">
            <FileText className="h-4 w-4 text-primary" />
          </div>
          <div className="min-w-0">
            <h2 className="text-sm font-semibold truncate leading-tight">{data.filename}</h2>
            <p className="text-[11px] text-muted-foreground font-medium uppercase tracking-wider">{data.content_type}</p>
          </div>
        </div>
        
        <div className="flex items-center gap-1">
          {isDirty && (
            <Button 
              variant="default" 
              size="sm" 
              className="h-8 gap-1.5 mr-2"
              onClick={handleSave}
              disabled={saving}
            >
              <Save className="h-3.5 w-3.5" />
              {saving ? 'Saving...' : 'Save'}
            </Button>
          )}
          <Button 
            variant="ghost" 
            size="icon" 
            className="h-8 w-8 text-muted-foreground hover:text-foreground"
            onClick={() => window.open(`/api/artifacts/${artifactId}/download`)}
            title="Open in new tab"
          >
            <ExternalLink className="h-4 w-4" />
          </Button>
          <Button 
            variant="ghost" 
            size="icon" 
            className="h-8 w-8 text-muted-foreground hover:text-foreground"
            onClick={onClose}
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
      </header>

      {/* Tabs */}
      <div className="flex items-center gap-1 px-4 py-1.5 border-b border-border/40 bg-muted/5">
        {isPreviewable && (
          <button
            onClick={() => setActiveTab('preview')}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${activeTab === 'preview' ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
          >
            <Eye className="h-3.5 w-3.5" /> Preview
          </button>
        )}
        <button
          onClick={() => setActiveTab('code')}
          className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${activeTab === 'code' ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
        >
          <Code className="h-3.5 w-3.5" /> Code
        </button>
        <button
          onClick={() => setActiveTab('download')}
          className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${activeTab === 'download' ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
        >
          <Download className="h-3.5 w-3.5" /> Download
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-hidden relative">
        {activeTab === 'preview' && (
          <div className="h-full w-full">
            {isHtml ? (
              <iframe
                srcDoc={editContent}
                sandbox="allow-scripts"
                className="w-full h-full border-none bg-white"
                title={data.filename}
              />
            ) : isMarkdown ? (
              <ScrollArea className="h-full">
                <MarkdownEditor 
                  content={editContent} 
                  onChange={handleContentChange} 
                />
              </ScrollArea>
            ) : (
              <ScrollArea className="h-full">
                <CodeEditor
                  content={editContent}
                  contentType={data.content_type}
                  onChange={handleContentChange}
                  onSave={handleSave}
                />
              </ScrollArea>
            )}
          </div>
        )}

        {activeTab === 'code' && (
          <CodeEditor
            content={editContent}
            contentType={data.content_type}
            onChange={handleContentChange}
            onSave={handleSave}
          />
        )}

        {activeTab === 'download' && (
          <div className="h-full flex items-center justify-center p-8 bg-muted/5">
            <div className="max-w-sm w-full">
              <ArtifactCard 
                artifact={{
                  id: artifactId,
                  filename: data.filename,
                  content_type: data.content_type,
                  file_size: data.file_size,
                  created_at: new Date().toISOString()
                }} 
              />
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
