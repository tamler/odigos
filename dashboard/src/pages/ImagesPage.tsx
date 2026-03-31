import { useEffect, useState, useRef, useCallback } from 'react'
import { useOutletContext } from 'react-router-dom'
import { get, del, uploadFile } from '@/lib/api'
import { Artifact } from '@/components/ArtifactCard'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Trash2, Upload, ImageIcon, Share2, Download, Camera } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { toast } from 'sonner'
import { Skeleton } from '@/components/ui/skeleton'

function ImageCard({ img, selected, onTap, onLongPress, onDelete, onDownload, onShare, onDismiss }: {
  img: Artifact
  selected: boolean
  onTap: () => void
  onLongPress: () => void
  onDelete: () => void
  onDownload: (e: React.MouseEvent) => void
  onShare: (e: React.MouseEvent) => void
  onDismiss: () => void
}) {
  const lp = useLongPress(onLongPress, 400)

  const handleClick = () => {
    if (lp.wasLongPress()) return
    if (selected) { onDismiss(); return }
    onTap()
  }

  const formatDate = (dt: string | null | undefined) => {
    if (!dt) return 'Recently'
    try {
      const d = new Date(dt.endsWith('Z') ? dt : dt + 'Z')
      return isNaN(d.getTime()) ? 'Recently' : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
    } catch { return 'Recently' }
  }

  return (
    <div
      className={`group relative flex flex-col bg-card rounded-xl border overflow-hidden transition-all cursor-pointer ${selected ? 'border-primary ring-2 ring-primary/30 shadow-lg' : 'border-border/40 hover:shadow-md'}`}
      onClick={handleClick}
      {...lp}
    >
      <div className="aspect-square relative overflow-hidden bg-muted">
        <img
          src={`/api/artifacts/${img.id}/thumbnail?size=400`}
          alt={img.filename}
          className="w-full h-full object-cover transition-transform duration-300 group-hover:scale-105"
          loading="lazy"
        />
        {/* Desktop: hover overlay */}
        <div className="absolute inset-0 bg-black/30 opacity-0 group-hover:opacity-100 transition-opacity items-center justify-center gap-2 hidden lg:flex">
          <Button size="icon" variant="secondary" className="h-9 w-9 rounded-full" onClick={(e) => { e.stopPropagation(); onDownload(e) }}>
            <Download className="h-4 w-4" />
          </Button>
          <Button size="icon" variant="secondary" className="h-9 w-9 rounded-full" onClick={(e) => { e.stopPropagation(); onShare(e) }}>
            <Share2 className="h-4 w-4" />
          </Button>
          <Button size="icon" variant="destructive" className="h-9 w-9 rounded-full" onClick={(e) => { e.stopPropagation(); onDelete() }}>
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* Mobile: action bar on long-press */}
      {selected && (
        <div className="absolute bottom-0 left-0 right-0 z-50 bg-background/95 backdrop-blur-sm border-t border-border/40 flex items-center justify-around py-3 px-2 lg:hidden animate-in slide-in-from-bottom duration-200">
          <button onClick={(e) => { e.stopPropagation(); onDownload(e as any) }} className="flex flex-col items-center gap-1 text-muted-foreground active:text-primary transition-colors min-w-[60px]">
            <Download className="h-5 w-5" />
            <span className="text-[10px] font-bold uppercase">Save</span>
          </button>
          <button onClick={(e) => { e.stopPropagation(); onShare(e as any) }} className="flex flex-col items-center gap-1 text-muted-foreground active:text-primary transition-colors min-w-[60px]">
            <Share2 className="h-5 w-5" />
            <span className="text-[10px] font-bold uppercase">Share</span>
          </button>
          <button onClick={(e) => { e.stopPropagation(); onDelete() }} className="flex flex-col items-center gap-1 text-destructive/70 active:text-destructive transition-colors min-w-[60px]">
            <Trash2 className="h-5 w-5" />
            <span className="text-[10px] font-bold uppercase">Delete</span>
          </button>
        </div>
      )}

      <div className="p-3 bg-card/50 backdrop-blur-sm border-t border-border/5">
        <p className="text-xs font-medium truncate mb-0.5">{img.filename}</p>
        <p className="text-[10px] text-muted-foreground uppercase tracking-widest font-bold opacity-60">
          {formatDate(img.created_at)}
        </p>
      </div>
    </div>
  )
}

function useLongPress(callback: () => void, ms = 500) {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const activeRef = useRef(false)

  const start = useCallback(() => {
    activeRef.current = false
    timerRef.current = setTimeout(() => {
      activeRef.current = true
      callback()
    }, ms)
  }, [callback, ms])

  const clear = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = null
  }, [])

  return {
    onTouchStart: start,
    onTouchEnd: clear,
    onTouchMove: clear,
    wasLongPress: () => activeRef.current,
  }
}

export default function ImagesPage() {
  const [images, setImages] = useState<Artifact[]>([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const cameraInputRef = useRef<HTMLInputElement>(null)
  
  const { 
    setArtifactPanelOpen, 
    setActiveArtifactId,
    isMobile
  } = useOutletContext<any>()

  const loadImages = useCallback(() => {
    setLoading(true)
    get<{ artifacts: Artifact[] }>('/api/artifacts')
      .then((data) => {
        const filtered = (data.artifacts || []).filter(a => 
          a.content_type?.startsWith('image/')
        )
        setImages(filtered)
      })
      .catch(() => toast.error('Failed to load images'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    loadImages()
  }, [loadImages])

  async function handleDelete(id: string, e?: React.MouseEvent) {
    if (e) e.stopPropagation()
    if (!window.confirm('Delete this image?')) return
    try {
      await del(`/api/artifacts/${id}`)
      setImages((prev) => prev.filter((a) => a.id !== id))
      setSelectedId(null)
      toast.success('Image deleted')
    } catch {
      toast.error('Failed to delete image')
    }
  }

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    
    setUploading(true)
    try {
      await uploadFile(file)
      toast.success('Image uploaded')
      loadImages()
    } catch {
      toast.error('Failed to upload image')
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
      if (cameraInputRef.current) cameraInputRef.current.value = ''
    }
  }

  const openImage = (id: string) => {
    setActiveArtifactId(id)
    setArtifactPanelOpen(true)
  }

  const shareImage = async (e: React.MouseEvent, artifact: Artifact) => {
    e.stopPropagation()
    const url = `${window.location.origin}/api/artifacts/${artifact.id}/download`
    if (navigator.share) {
      try {
        await navigator.share({ title: artifact.filename, url })
      } catch (err) {
        if ((err as Error).name !== 'AbortError') toast.error('Failed to share')
      }
    } else {
      await navigator.clipboard.writeText(url)
      toast.success('Link copied to clipboard')
    }
  }

  const downloadImage = (e: React.MouseEvent, artifact: Artifact) => {
    e.stopPropagation()
    const link = document.createElement('a')
    link.href = `/api/artifacts/${artifact.id}/download`
    link.download = artifact.filename
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }

  return (
    <div className="flex flex-col h-full bg-background overflow-hidden p-4 lg:p-8 max-w-7xl mx-auto w-full text-foreground">
      <div className="flex items-center justify-between mb-6 lg:mb-8 shrink-0 pl-12 lg:pl-0">
        <div>
          <h1 className="text-2xl lg:text-3xl font-bold tracking-tight">Images</h1>
          <p className="text-muted-foreground mt-1 text-sm lg:text-base">Gallery of all generated and uploaded images.</p>
        </div>
        <div className="flex gap-2">
          {isMobile && (
            <Button variant="ghost" size="icon" onClick={() => cameraInputRef.current?.click()} disabled={uploading} className="h-9 w-9 text-muted-foreground hover:text-foreground">
              <Camera className="h-4 w-4" />
            </Button>
          )}
          <Button variant="ghost" size="icon" onClick={() => fileInputRef.current?.click()} disabled={uploading} className="h-9 w-9 text-muted-foreground hover:text-foreground">
            <Upload className="h-4 w-4" />
          </Button>
        </div>
        <input type="file" ref={fileInputRef} onChange={handleUpload} accept="image/*" className="hidden" />
        <input type="file" ref={cameraInputRef} onChange={handleUpload} accept="image/*" capture="environment" className="hidden" />
      </div>

      <ScrollArea className="flex-1 -mx-4 px-4">
        {loading ? (
          <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4 pb-8">
            {[1, 2, 3, 4, 5, 6, 7, 8].map((i) => (
              <Skeleton key={i} className="aspect-square w-full rounded-xl" />
            ))}
          </div>
        ) : images.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-32 text-center">
            <div className="h-16 w-16 rounded-2xl bg-primary/10 flex items-center justify-center mb-4">
              <ImageIcon className="text-primary h-8 w-8" />
            </div>
            <h3 className="text-lg font-medium text-foreground mb-1">No images yet</h3>
            <p className="text-muted-foreground text-sm max-w-sm px-4">
              Ask your agent to generate an image or upload one yourself.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4 lg:gap-6 pb-8">
            {images.map((img) => (
              <ImageCard
                key={img.id}
                img={img}
                selected={selectedId === img.id}
                onTap={() => openImage(img.id)}
                onLongPress={() => setSelectedId(img.id)}
                onDelete={() => handleDelete(img.id)}
                onDownload={(e) => downloadImage(e, img)}
                onShare={(e) => shareImage(e, img)}
                onDismiss={() => setSelectedId(null)}
              />
            ))}
          </div>
        )}
      </ScrollArea>
      {selectedId && (
        <div className="fixed inset-0 z-40 lg:hidden" onClick={() => setSelectedId(null)} />
      )}
    </div>
  )
}
