/**
 * Image cropper using Cropper.js v2.
 * Opens as a modal overlay, sends crop coordinates to the backend.
 */
import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { X, Check } from 'lucide-react'
import { toast } from 'sonner'
import Cropper from 'cropperjs'
import 'cropperjs/dist/cropper.css'

interface ImageCropperProps {
  imageUrl: string
  artifactId: string
  filename: string
  onClose: () => void
  onCropped?: () => void
}

export function ImageCropper({ imageUrl, artifactId: _artifactId, filename, onClose, onCropped }: ImageCropperProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const cropperRef = useRef<any>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let cropper: any = null

    async function init() {
      if (!containerRef.current) return

      const img = document.createElement('img')
      img.src = imageUrl
      img.style.maxWidth = '100%'
      containerRef.current.innerHTML = ''
      containerRef.current.appendChild(img)

      cropper = new Cropper(img, {
        // v2 options
      })
      cropperRef.current = cropper
    }

    init()
    return () => {
      if (cropper && cropper.destroy) cropper.destroy()
    }
  }, [imageUrl])

  async function handleCrop() {
    const cropper = cropperRef.current
    if (!cropper) return

    setSaving(true)
    try {
      // Get crop data from Cropper.js
      const data = cropper.getData(true)
      const cropBox = `${Math.round(data.x)},${Math.round(data.y)},${Math.round(data.x + data.width)},${Math.round(data.y + data.height)}`

      // Send to backend process_image tool via API
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          content: `Crop the image ${filename} with coordinates: ${cropBox}`,
        }),
      })

      if (res.ok) {
        toast.success('Image cropped')
        onCropped?.()
      } else {
        toast.error('Failed to crop image')
      }
    } catch {
      toast.error('Crop failed')
    } finally {
      setSaving(false)
      onClose()
    }
  }

  return (
    <div className="fixed inset-0 z-[60] bg-background flex flex-col">
      <div className="flex items-center justify-between px-4 py-3 border-b border-border/40">
        <h3 className="text-sm font-semibold">Crop Image</h3>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="ghost" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
          <Button size="sm" onClick={handleCrop} disabled={saving}>
            <Check className="h-4 w-4 mr-1" />
            {saving ? 'Saving...' : 'Apply Crop'}
          </Button>
        </div>
      </div>
      <div ref={containerRef} className="flex-1 overflow-hidden p-4 bg-muted/10" />
    </div>
  )
}
