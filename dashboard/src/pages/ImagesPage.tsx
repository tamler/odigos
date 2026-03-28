import { useEffect, useState, useRef, useCallback } from 'react'
import { useOutletContext } from 'react-router-dom'
import { get, del, uploadFile } from '@/lib/api'
import { Artifact } from '@/components/ArtifactCard'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Trash2, Upload, ImageIcon, Share2, Download, Camera } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { toast } from 'sonner'
import { Skeleton } from '@/components/ui/skeleton'

export default function ImagesPage() {
  const [images, setImages] = useState<Artifact[]>([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
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

  async function handleDelete(e: React.MouseEvent, id: string) {
    e.stopPropagation()
    if (!window.confirm('Delete this image?')) return
    try {
      await del(`/api/artifacts/${id}`)
      setImages((prev) => prev.filter((a) => a.id !== id))
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
    const url = `${window.location.origin}/api/files/${artifact.filename}`
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
      <div className="flex items-center justify-between mb-6 lg:mb-8 shrink-0">
        <div>
          <h1 className="text-2xl lg:text-3xl font-bold tracking-tight">Images</h1>
          <p className="text-muted-foreground mt-1 text-sm lg:text-base">Gallery of all generated and uploaded images.</p>
        </div>
        <div className="flex gap-2">
          {isMobile && (
            <Button variant="outline" size="icon" onClick={() => cameraInputRef.current?.click()} disabled={uploading} className="h-10 w-10">
              <Camera className="h-5 w-5" />
            </Button>
          )}
          <Button onClick={() => fileInputRef.current?.click()} disabled={uploading} className="gap-2 h-10 px-4">
            <Upload className="h-4 w-4" />
            <span className="hidden sm:inline">{uploading ? 'Uploading...' : 'Upload'}</span>
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
              <div 
                key={img.id} 
                className="group relative flex flex-col bg-card rounded-xl border border-border/40 overflow-hidden hover:shadow-md transition-all cursor-pointer"
                onClick={() => openImage(img.id)}
              >
                <div className="aspect-square relative overflow-hidden bg-muted">
                  <img 
                    src={`/api/files/${img.filename}`} 
                    alt={img.filename}
                    className="w-full h-full object-cover transition-transform duration-300 group-hover:scale-105"
                    loading="lazy"
                  />
                  <div className="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center gap-2">
                    <Button size="icon" variant="secondary" className="h-8 w-8 rounded-full" onClick={(e) => downloadImage(e, img)}>
                      <Download className="h-4 w-4" />
                    </Button>
                    <Button size="icon" variant="secondary" className="h-8 w-8 rounded-full" onClick={(e) => shareImage(e, img)}>
                      <Share2 className="h-4 w-4" />
                    </Button>
                    <Button size="icon" variant="destructive" className="h-8 w-8 rounded-full" onClick={(e) => handleDelete(e, img.id)}>
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
                <div className="p-3 bg-card/50 backdrop-blur-sm border-t border-border/5">
                  <p className="text-xs font-medium truncate mb-0.5">{img.filename}</p>
                  <p className="text-[10px] text-muted-foreground uppercase tracking-widest font-bold opacity-60">
                    {img.created_at ? new Date(img.created_at + 'Z').toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : 'Recently'}
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}
      </ScrollArea>
    </div>
  )
}
