import { useState, useEffect } from 'react'
import { useOutletContext } from 'react-router-dom'
import { get, put } from '@/lib/api'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { X, ExternalLink, Download, Code, Eye, FileText, Save, FileDown, BookOpen, Image as ImageIcon, Sparkles, Crop } from 'lucide-react'
import { ImageCropper } from './ImageCropper'
import { ArtifactCard } from './ArtifactCard'
import { MarkdownEditor, CodeEditor } from './Editor'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

// @ts-ignore
import html2pdf from 'html2pdf.js'
// @ts-ignore
import { epub } from 'epub-gen-memory'

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
  const { setPageContextData, setChatPanelOpen } = useOutletContext<any>()
  const [data, setData] = useState<ArtifactContent | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [activeTab, setActiveTab] = useState<PreviewTab>('preview')
  const [editContent, setEditContent] = useState('')
  const [isDirty, setIsDirty] = useState(false)
  const [exporting, setExporting] = useState(false)
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
          // Default to preview for images, download for binary non-images
          const isImg = res.content_type.startsWith('image/')
          const isText = res.content_type.startsWith('text/') ||
                         res.content_type === 'application/json' ||
                         res.content_type === 'application/xml'
          if (isImg) setActiveTab('preview')
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

  const handleExportPDF = async () => {
    if (!data) return
    setExporting(true)
    try {
      const element = document.createElement('div')
      element.className = 'prose prose-sm p-8 bg-white text-black'
      
      // Simple markdown to basic HTML conversion if it's markdown
      if (data.content_type === 'text/markdown') {
        element.innerHTML = `<h1 style="font-size: 24px; margin-bottom: 20px;">${data.filename}</h1>` + 
                           editContent.replace(/\n/g, '<br/>')
      } else {
        element.innerHTML = editContent
      }

      const opt = {
        margin: 1,
        filename: `${data.filename.split('.')[0]}.pdf`,
        image: { type: 'jpeg' as const, quality: 0.98 },
        html2canvas: { scale: 2 },
        jsPDF: { unit: 'in' as const, format: 'letter' as const, orientation: 'portrait' as const }
      }

      await html2pdf().from(element).set(opt).save()
      toast.success('PDF exported')
    } catch (err) {
      console.error(err)
      toast.error('Failed to export PDF')
    } finally {
      setExporting(false)
    }
  }

  const handleExportEPUB = async () => {
    if (!data) return
    setExporting(true)
    try {
      const content = [
        {
          title: data.filename,
          data: editContent.replace(/\n/g, '<br/>')
        }
      ]
      
      const option = {
        title: data.filename.split('.')[0],
        author: 'Odigos Agent',
        content
      }

      const result = await epub(option, [])
      const blob = new Blob([result], { type: 'application/epub+zip' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${data.filename.split('.')[0]}.epub`
      a.click()
      URL.revokeObjectURL(url)
      toast.success('ePub exported')
    } catch (err) {
      console.error(err)
      toast.error('Failed to export ePub')
    } finally {
      setExporting(false)
    }
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
  const isPreviewable = isHtml || isMarkdown || data.content_type.startsWith('text/') || isJson || isImage

  const handleEditWithAgent = () => {
    setChatPanelOpen(true)
    toast.info('Chat opened. Tell the agent how to edit this image.')
  }

  return (
    <div className="flex-1 flex flex-col h-full bg-background border-l border-border/40 overflow-hidden shadow-2xl">
      {/* Header */}
      <header className="flex items-center justify-between px-4 py-3 border-b border-border/40 bg-muted/5">
        <div className="flex items-center gap-3 min-w-0">
          <div className="p-2 bg-primary/10 rounded-lg shrink-0">
            {isImage ? <ImageIcon className="h-4 w-4 text-primary" /> : <FileText className="h-4 w-4 text-primary" />}
          </div>
          <div className="min-w-0">
            <h2 className="text-sm font-semibold truncate leading-tight">{data.filename}</h2>
            <p className="text-[11px] text-muted-foreground font-medium uppercase tracking-wider">{data.content_type}</p>
          </div>
        </div>
        
        <div className="flex items-center gap-1">
          {isImage && (
            <>
              <Button
                variant="outline"
                size="sm"
                className="h-8 gap-1.5 mr-1 border-primary/20 text-primary hover:bg-primary/5"
                onClick={() => setCropOpen(true)}
              >
                <Crop className="h-3.5 w-3.5" />
                Crop
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="h-8 gap-1.5 mr-2 border-primary/20 text-primary hover:bg-primary/5"
                onClick={handleEditWithAgent}
              >
                <Sparkles className="h-3.5 w-3.5" />
                Edit with Agent
              </Button>
            </>
          )}
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

          <DropdownMenu>
            <DropdownMenuTrigger>
              <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground hover:text-foreground">
                <FileDown className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={() => window.open(`/api/artifacts/${artifactId}/download`)}>
                <Download className="h-4 w-4 mr-2" /> Download Raw
              </DropdownMenuItem>
              <DropdownMenuItem onClick={handleExportPDF} disabled={exporting}>
                <FileText className="h-4 w-4 mr-2" /> Export as PDF
              </DropdownMenuItem>
              <DropdownMenuItem onClick={handleExportEPUB} disabled={exporting}>
                <BookOpen className="h-4 w-4 mr-2" /> Export as ePub
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>

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
            {isImage ? <ImageIcon className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />} 
            {isImage ? 'View' : 'Preview'}
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
                  onLoad={(e) => {
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
          onCropped={() => { setCropOpen(false); window.location.reload() }}
        />
      )}
    </div>
  )
}
