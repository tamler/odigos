import { useState } from 'react'
import { post, del } from '@/lib/api'
import { toast } from 'sonner'
import { 
  Dialog, 
  DialogContent, 
  DialogHeader, 
  DialogTitle,
  DialogDescription,
  DialogFooter
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Copy, Trash2, Globe, Link as LinkIcon, Loader2 } from 'lucide-react'

interface ShareDialogProps {
  type: 'notebook' | 'board'
  id: string
  isOpen: boolean
  onClose: () => void
  initialShareToken?: string | null
}

export function ShareDialog({ type, id, isOpen, onClose, initialShareToken }: ShareDialogProps) {
  const [token, setToken] = useState<string | null>(initialShareToken || null)
  const [loading, setLoading] = useState(false)
  const [revoking, setRevoking] = useState(false)

  if (!id) return null

  const shareUrl = token ? `${window.location.origin}/shared/${type}/${token}` : ''

  async function handleCreateShare() {
    setLoading(true)
    try {
      const endpoint = type === 'notebook' ? `/api/notebooks/${id}/share` : `/api/kanban/boards/${id}/share`
      const res = await post<{ share_token: string }>(endpoint, {})
      setToken(res.share_token)
      toast.success('Share link generated')
    } catch {
      toast.error('Failed to generate share link')
    } finally {
      setLoading(false)
    }
  }

  async function handleRevokeShare() {
    setRevoking(true)
    try {
      const endpoint = type === 'notebook' ? `/api/notebooks/${id}/share` : `/api/kanban/boards/${id}/share`
      await del(endpoint)
      setToken(null)
      toast.success('Share link revoked')
    } catch {
      toast.error('Failed to revoke share link')
    } finally {
      setRevoking(false)
    }
  }

  function copyToClipboard() {
    navigator.clipboard.writeText(shareUrl)
    toast.success('Link copied to clipboard')
  }

  return (
    <Dialog open={isOpen} onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Globe className="h-5 w-5 text-primary" />
            Share {type === 'notebook' ? 'Notebook' : 'Board'}
          </DialogTitle>
          <DialogDescription>
            Anyone with this link can view a read-only version of this {type}.
          </DialogDescription>
        </DialogHeader>

        <div className="py-4">
          {!token ? (
            <div className="flex flex-col items-center justify-center py-6 border-2 border-dashed border-border/60 rounded-xl bg-muted/20">
              <LinkIcon className="h-10 w-10 text-muted-foreground/40 mb-3" />
              <p className="text-sm text-muted-foreground mb-4">No active share link</p>
              <Button onClick={handleCreateShare} disabled={loading}>
                {loading ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
                Create Public Link
              </Button>
            </div>
          ) : (
            <div className="space-y-4">
              <div className="flex items-center gap-2">
                <Input 
                  value={shareUrl} 
                  readOnly 
                  className="bg-muted font-mono text-[11px]" 
                />
                <Button size="icon" variant="outline" onClick={copyToClipboard} title="Copy Link">
                  <Copy className="h-4 w-4" />
                </Button>
              </div>
              <p className="text-[11px] text-muted-foreground italic">
                Note: This link is public. Anyone who has it can see your {type}.
              </p>
            </div>
          )}
        </div>

        <DialogFooter className="sm:justify-between items-center">
          {token && (
            <Button 
              type="button" 
              variant="ghost" 
              size="sm" 
              className="text-destructive hover:text-destructive hover:bg-destructive/10 h-8"
              onClick={handleRevokeShare}
              disabled={revoking}
            >
              {revoking ? <Loader2 className="h-3 w-3 animate-spin mr-2" /> : <Trash2 className="h-3.5 w-3.5 mr-2" />}
              Revoke Link
            </Button>
          )}
          <Button type="button" variant="secondary" size="sm" onClick={onClose} className="h-8 ml-auto">
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
