import { useEffect, useState, useCallback } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { get, post, patch } from '@/lib/api'
import { toast } from 'sonner'
import { Trash2, Activity, Network, Plus } from 'lucide-react'

interface Peer {
  name: string
  netbird_ip: string
  ws_port: number
  api_key: string
}

interface SettingsData {
  peers?: Peer[]
}

export default function PeerConfigTab() {
  const [peers, setPeers] = useState<Peer[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  
  // New peer form state
  const [newName, setNewName] = useState('')
  const [newIp, setNewIp] = useState('')
  const [newPort, setNewPort] = useState(8000)
  const [newApiKey, setNewApiKey] = useState('')

  const loadSettings = useCallback(() => {
    setLoading(true)
    get<SettingsData>('/api/settings')
      .then((data) => {
        if (data?.peers) setPeers(data.peers)
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { loadSettings() }, [loadSettings])

  async function handleAddPeer(e: React.FormEvent) {
    e.preventDefault()
    if (!newName || !newIp || !newApiKey) return
    
    const newPeer: Peer = {
      name: newName.trim(),
      netbird_ip: newIp.trim(),
      ws_port: newPort,
      api_key: newApiKey.trim()
    }
    
    const updatedPeers = [...peers, newPeer]
    await savePeers(updatedPeers)
    
    // Reset form
    setNewName('')
    setNewIp('')
    setNewPort(8000)
    setNewApiKey('')
  }
  
  async function handleRemovePeer(name: string) {
    if (!window.confirm(`Delete peer connection to ${name}?`)) return
    const updatedPeers = peers.filter(p => p.name !== name)
    await savePeers(updatedPeers)
  }

  async function savePeers(updatedPeers: Peer[]) {
    setSaving(true)
    try {
      await patch('/api/settings', { peers: updatedPeers })
      setPeers(updatedPeers)
      toast.success('Peer configuration saved')
    } catch {
      toast.error('Failed to update peers')
    } finally {
      setSaving(false)
    }
  }

  async function testConnection(name: string) {
    const toastId = toast.loading(`Pinging ${name}...`)
    try {
      const res = await post<{ reachable: boolean; latency_ms?: number }>(`/api/mesh/peers/${name}/ping`, {})
      if (res.reachable) {
        toast.success(`Connection successful (${res.latency_ms}ms latency)`, { id: toastId })
      } else {
        toast.error(`Host unreachable`, { id: toastId })
      }
    } catch {
      toast.error('Ping request failed', { id: toastId })
    }
  }

  if (loading) return <div className="p-6 text-sm text-muted-foreground">Loading peer configuration...</div>

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 py-4 sm:py-6 space-y-6">
      <div className="flex items-center gap-2 pb-2 border-b border-border/40">
        <Network className="h-5 w-5 text-primary" />
        <h2 className="text-lg font-semibold tracking-tight">Mesh Nodes</h2>
      </div>
      
      {/* Existing Peers */}
      <div className="space-y-4">
        {peers.length === 0 ? (
           <div className="p-8 text-center border border-dashed rounded-lg bg-muted/30">
             <p className="text-muted-foreground text-sm">No external peers currently tracked in settings.</p>
           </div>
        ) : (
          <div className="grid gap-3">
            {peers.map((peer) => (
              <div key={peer.name} className="flex flex-col sm:flex-row gap-4 justify-between items-start sm:items-center p-4 rounded-lg border border-border/40 bg-card">
                <div>
                  <h4 className="font-medium">{peer.name}</h4>
                  <div className="text-xs text-muted-foreground mt-1 flex gap-3">
                    <span>{peer.netbird_ip}:{peer.ws_port}</span>
                    <span>Key: ••••••••</span>
                  </div>
                </div>
                <div className="flex gap-2">
                  <Button variant="secondary" size="sm" onClick={() => testConnection(peer.name)} className="h-8">
                    <Activity className="h-4 w-4 mr-1.5" /> Ping
                  </Button>
                  <Button variant="destructive" size="sm" onClick={() => handleRemovePeer(peer.name)} className="h-8 w-8 p-0" aria-label={`Remove ${peer.name}`}>
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Add New Peer */}
      <div className="rounded-lg border border-border/40 bg-card mt-6">
        <div className="px-5 py-3 border-b border-border/40">
          <h3 className="text-sm font-medium">Register New Peer</h3>
        </div>
        <form onSubmit={handleAddPeer} className="p-5 space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label className="text-xs">Peer Identity (Name)</Label>
              <Input required value={newName} onChange={e => setNewName(e.target.value)} placeholder="e.g. Odigos Support Node" className="bg-muted/50" />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Auth Key (Recipient's Dashboard API Key)</Label>
              <Input required type="password" value={newApiKey} onChange={e => setNewApiKey(e.target.value)} placeholder="****" className="bg-muted/50" />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Netbird IP / Hostname</Label>
              <Input required value={newIp} onChange={e => setNewIp(e.target.value)} placeholder="100.x.y.z" className="bg-muted/50" />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">WebSocket Port</Label>
              <Input required type="number" value={newPort} onChange={e => setNewPort(Number(e.target.value))} className="bg-muted/50" />
            </div>
          </div>
          <div className="flex justify-end pt-2">
            <Button type="submit" disabled={saving}>
              <Plus className="h-4 w-4 mr-2" />
              Add Node
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}
