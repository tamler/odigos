import { useState, useEffect } from 'react'
import { useOutletContext, useSearchParams } from 'react-router-dom'
import { get, put, post } from '@/lib/api'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { ScrollArea } from '@/components/ui/scroll-area'
import { X, ExternalLink, Download, Code, Eye, FileText, Save, Music, Send } from 'lucide-react'
import { ImageCropper } from './ImageCropper'
import { ArtifactCard } from './ArtifactCard'
import { MarkdownEditor, CodeEditor } from './Editor'

// @ts-ignore
import html2pdf from 'html2pdf.js'
// @ts-ignore
import { epub } from 'epub-gen-memory'

interface SongData {
  title?: string
  lyrics?: string
  style?: string
  instrumental?: boolean
  vocal_gender?: '' | 'male' | 'female'
  [key: string]: unknown
}

function SongEditor({
  content,
  artifactId,
  conversationId,
  onChange,
  onSave,
}: {
  content: string
  artifactId: string
  conversationId: string | null
  onChange: (newContent: string) => void
  onSave: () => void
}) {
  const [song, setSong] = useState<SongData>(() => {
    try { return JSON.parse(content) } catch { return {} }
  })
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    try { setSong(JSON.parse(content)) } catch {}
  }, [content])

  const update = (field: keyof SongData, value: unknown) => {
    const updated = { ...song, [field]: value }
    setSong(updated)
    onChange(JSON.stringify(updated, null, 2))
  }

  const handleGenerate = async () => {
    if (!conversationId) {
      toast.error('No active conversation')
      return
    }
    onSave()
    setSubmitting(true)
    try {
      await post(`/api/conversations/${conversationId}/messages`, {
        content: `Submit the song draft ${artifactId}`,
      })
      toast.success('Song submitted for generation')
    } catch {
      toast.error('Failed to submit song')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="p-6 space-y-5 max-w-2xl mx-auto">
      <div className="flex items-center gap-2 mb-2">
        <Music className="h-5 w-5 text-primary" />
        <h3 className="text-base font-semibold">Song Editor</h3>
      </div>

      <div className="space-y-2">
        <Label htmlFor="song-title">Title</Label>
        <Input
          id="song-title"
          value={song.title || ''}
          onChange={(e) => update('title', e.target.value)}
          placeholder="Song title"
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="song-lyrics">Lyrics</Label>
        <Textarea
          id="song-lyrics"
          value={song.lyrics || ''}
          onChange={(e) => update('lyrics', e.target.value)}
          placeholder="Write your lyrics here..."
          className="min-h-[200px] font-mono text-sm resize-y"
          rows={12}
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="song-style">Style / Genre</Label>
        <Input
          id="song-style"
          value={song.style || ''}
          onChange={(e) => update('style', e.target.value)}
          placeholder="e.g. upbeat pop, acoustic folk, lo-fi hip hop"
        />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label>Instrumental</Label>
          <button
            type="button"
            onClick={() => update('instrumental', !song.instrumental)}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
              song.instrumental ? 'bg-primary' : 'bg-muted-foreground/30'
            }`}
          >
            <span
              className={`inline-block h-4 w-4 rounded-full bg-white transition-transform ${
                song.instrumental ? 'translate-x-6' : 'translate-x-1'
              }`}
            />
          </button>
        </div>

        <div className="space-y-2">
          <Label>Vocal Gender</Label>
          <Select
            value={song.vocal_gender || ''}
            onValueChange={(v) => update('vocal_gender', v)}
          >
            <SelectTrigger className="w-full">
              <SelectValue placeholder="Any" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="">Any</SelectItem>
              <SelectItem value="male">Male</SelectItem>
              <SelectItem value="female">Female</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="pt-2">
        <Button
          onClick={handleGenerate}
          disabled={submitting || !song.title}
          className="gap-2"
        >
          <Send className="h-4 w-4" />
          {submitting ? 'Submitting...' : 'Generate Song'}
        </Button>
      </div>
    </div>
  )
}

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
  const [searchParams] = useSearchParams()
  let outletCtx: any = {}
  try { outletCtx = useOutletContext<any>() || {} } catch { outletCtx = {} }
  const { setPageContextData = () => {} } = outletCtx
  const conversationId = searchParams.get('c') || null
  const [data, setData] = useState<ArtifactContent | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [activeTab, setActiveTab] = useState<PreviewTab>('preview')
  const [editContent, setEditContent] = useState('')
  const [isDirty, setIsDirty] = useState(false)
  const [cropOpen, setCropOpen] = useState(false)

  useEffect(() => {
    if (data) {
      setPageContextData({
        page_id: artifactId,
        page_title: data.filename,
        visible_data: `Type: ${data.content_type}, Size: ${data.file_size} bytes`
      })
    }
    return () => setPageContextData({})
  }, [data, artifactId, setPageContextData])

  useEffect(() => {
    let mounted = true
    setLoading(true)
    get<ArtifactContent>(`/api/artifacts/${artifactId}/content`)
      .then((res) => {
        if (mounted) {
          setData(res)
          setEditContent(res.content)
          setIsDirty(false)
          // Default to preview for images/audio, download for binary non-images
          const isImg = res.content_type.startsWith('image/')
          const isAud = res.content_type.startsWith('audio/')
          const isText = res.content_type.startsWith('text/') ||
                         res.content_type === 'application/json' ||
                         res.content_type === 'application/xml'
          if (isImg || isAud) setActiveTab('preview')
          else if (!isText) setActiveTab('download')
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
  const isImage = data.content_type.startsWith('image/')
  const isAudio = data.content_type.startsWith('audio/')
  const isSongJson = isJson && data.filename.endsWith('.song.json')
  const isPreviewable = isHtml || isMarkdown || data.content_type.startsWith('text/') || isJson || isImage || isAudio


  // Audio gets a dedicated player view
  if (isAudio) {
    const formatLabel = data.content_type.replace('audio/', '').toUpperCase()
    return (
      <div className="flex-1 flex flex-col h-full bg-background border-l border-border/40 overflow-hidden shadow-2xl">
        <header className="flex items-center justify-between px-4 py-3 border-b border-border/40 bg-muted/5">
          <div className="flex items-center gap-3 min-w-0">
            <div className="p-2 bg-primary/10 rounded-lg shrink-0">
              <Music className="h-4 w-4 text-primary" />
            </div>
            <div className="min-w-0">
              <h2 className="text-sm font-semibold truncate leading-tight">{data.filename}</h2>
            </div>
          </div>
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground hover:text-foreground"
              onClick={() => { const a = document.createElement('a'); a.href = `/api/artifacts/${artifactId}/download`; a.download = data.filename; a.click() }}
              title="Download">
              <Download className="h-4 w-4" />
            </Button>
            <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground hover:text-foreground" onClick={onClose}>
              <X className="h-4 w-4" />
            </Button>
          </div>
        </header>

        <div className="flex-1 flex items-center justify-center p-8 bg-muted/5">
          <div className="w-full max-w-md space-y-6">
            <div className="rounded-xl border border-border/40 bg-card p-6 shadow-sm space-y-4">
              <div className="flex items-center gap-3">
                <div className="h-12 w-12 bg-primary/10 rounded-lg flex items-center justify-center shrink-0">
                  <Music className="h-6 w-6 text-primary" />
                </div>
                <div className="min-w-0">
                  <p className="text-sm font-semibold truncate">{data.filename}</p>
                  <p className="text-xs text-muted-foreground">
                    {formatLabel} &middot; {data.file_size < 1024 * 1024
                      ? `${(data.file_size / 1024).toFixed(1)} KB`
                      : `${(data.file_size / (1024 * 1024)).toFixed(1)} MB`}
                  </p>
                </div>
              </div>

              <audio
                controls
                preload="metadata"
                className="w-full"
                src={`/api/artifacts/${artifactId}/download`}
              >
                Your browser does not support the audio element.
              </audio>
            </div>

            <div className="flex justify-center">
              <Button
                variant="outline"
                className="gap-2"
                onClick={() => { const a = document.createElement('a'); a.href = `/api/artifacts/${artifactId}/download`; a.download = data.filename; a.click() }}
              >
                <Download className="h-4 w-4" />
                Download {formatLabel}
              </Button>
            </div>
          </div>
        </div>
      </div>
    )
  }

  // Images get a clean, simple header. Text files get tabs.
  if (isImage) {
    return (
      <div className="flex-1 flex flex-col h-full bg-black">
        {/* Close button top-left, minimal */}
        <div className="absolute top-4 left-4 z-10">
          <Button variant="ghost" size="icon" className="h-10 w-10 text-white/50 hover:text-white bg-black/30 rounded-full" onClick={onClose}>
            <X className="h-5 w-5" />
          </Button>
        </div>

        {/* Image centered */}
        <div className="flex-1 flex items-center justify-center p-4 overflow-auto">
          <img
            src={`/api/artifacts/${artifactId}/download`}
            alt={data.filename}
            className="max-w-full max-h-full object-contain"
            onError={(e) => {
              const target = e.target as HTMLImageElement
              target.style.display = 'none'
              target.parentElement!.insertAdjacentHTML('beforeend', '<p class="text-white/50 text-sm">Failed to load image</p>')
            }}
          />
        </div>

        {/* Action buttons at the bottom where thumbs are */}
        <div className="flex items-center justify-center gap-6 px-6 py-4 pb-safe bg-black/90 shrink-0">
          <Button variant="ghost" size="icon" className="h-12 w-12 text-white/70 hover:text-white rounded-full"
            onClick={() => { const a = document.createElement('a'); a.href = `/api/artifacts/${artifactId}/download`; a.download = data.filename; a.click() }}
          >
            <Download className="h-6 w-6" />
          </Button>
          <Button variant="ghost" size="icon" className="h-12 w-12 text-white/70 hover:text-white rounded-full"
            onClick={async () => {
              const url = `${window.location.origin}/api/artifacts/${artifactId}/download`
              if (navigator.share) { try { await navigator.share({ title: data.filename, url }) } catch {} }
              else { await navigator.clipboard.writeText(url); toast.success('Link copied') }
            }}
          >
            <ExternalLink className="h-6 w-6" />
          </Button>
        </div>

        {cropOpen && (
          <ImageCropper
            imageUrl={`/api/artifacts/${artifactId}/download`}
            artifactId={artifactId}
            filename={data.filename}
            onClose={() => setCropOpen(false)}
            onCropped={() => {
              setCropOpen(false)
              get<ArtifactContent>(`/api/artifacts/${artifactId}/content`)
                .then((res) => { setData(res); setEditContent(res.content) })
                .catch(() => {})
            }}
          />
        )}
      </div>
    )
  }

  return (
    <div className="flex-1 flex flex-col h-full bg-background border-l border-border/40 overflow-hidden shadow-2xl">
      {/* Header for text/document files */}
      <header className="flex items-center justify-between px-4 py-3 border-b border-border/40 bg-muted/5">
        <div className="flex items-center gap-3 min-w-0">
          <div className="p-2 bg-primary/10 rounded-lg shrink-0">
            <FileText className="h-4 w-4 text-primary" />
          </div>
          <div className="min-w-0">
            <h2 className="text-sm font-semibold truncate leading-tight">{data.filename}</h2>
          </div>
        </div>
        <div className="flex items-center gap-1">
          {isDirty && (
            <Button variant="default" size="sm" className="h-8 gap-1.5 mr-2" onClick={handleSave} disabled={saving}>
              <Save className="h-3.5 w-3.5" />
              {saving ? 'Saving...' : 'Save'}
            </Button>
          )}
          <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground hover:text-foreground"
            onClick={() => window.open(`/api/artifacts/${artifactId}/download`)} title="Download">
            <Download className="h-4 w-4" />
          </Button>
          <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground hover:text-foreground" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
        </div>
      </header>

      {/* Tabs for text files only */}
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
      <div className="flex-1 overflow-auto relative" style={{ minHeight: '200px' }}>
        {activeTab === 'preview' && (
          <div className="w-full h-full min-h-[200px]">
            {isImage ? (
              <div className="w-full h-full min-h-[200px] flex items-center justify-center p-4 lg:p-12 bg-muted/10 relative">
                <div className="absolute inset-0 flex items-center justify-center pointer-events-none" id={`loader-${artifactId}`}>
                  <div className="h-6 w-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                </div>
                <img
                  src={`/api/artifacts/${artifactId}/download`}
                  alt={data.filename}
                  className="max-w-full max-h-[70vh] object-contain rounded-lg shadow-xl relative z-10"
                  onLoad={() => {
                    const loader = document.getElementById(`loader-${artifactId}`)
                    if (loader) loader.style.display = 'none'
                  }}
                  onError={(e) => {
                    const loader = document.getElementById(`loader-${artifactId}`)
                    if (loader) loader.style.display = 'none'
                    const target = e.target as HTMLImageElement
                    target.style.display = 'none'
                    target.parentElement!.insertAdjacentHTML('beforeend', '<p class="text-muted-foreground text-sm relative z-10">Failed to load image</p>')
                  }}
                />
              </div>
            ) : isSongJson ? (
              <ScrollArea className="h-full">
                <SongEditor
                  content={editContent}
                  artifactId={artifactId}
                  conversationId={conversationId}
                  onChange={handleContentChange}
                  onSave={handleSave}
                />
              </ScrollArea>
            ) : isHtml ? (
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

      {cropOpen && isImage && (
        <ImageCropper
          imageUrl={`/api/artifacts/${artifactId}/download`}
          artifactId={artifactId}
          filename={data.filename}
          onClose={() => setCropOpen(false)}
          onCropped={() => {
              setCropOpen(false)
              get<ArtifactContent>(`/api/artifacts/${artifactId}/content`)
                .then((res) => { setData(res); setEditContent(res.content) })
                .catch(() => {})
            }}
        />
      )}
    </div>
  )
}
