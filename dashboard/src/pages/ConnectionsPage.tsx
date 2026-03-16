import { useState, useEffect, useCallback } from 'react'
import { get, post } from '@/lib/api'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Link2, Copy, X, Clock } from 'lucide-react'

interface IssuedCard {
  card_key: string
  card_type: string
  issued_to: string
  status: string
  created_at: string
  last_used_at: string | null
}

interface AcceptedCard {
  card_id: string
  agent_name: string
  card_type: string
  host: string
  status: string
  last_connected_at: string | null
}

interface GeneratedCard {
  yaml: string
  compact: string
}

export default function ConnectionsPage() {
  const [tab, setTab] = useState<'issued' | 'accepted'>('issued')
  const [issued, setIssued] = useState<IssuedCard[]>([])
  const [accepted, setAccepted] = useState<AcceptedCard[]>([])
  const [showGenerate, setShowGenerate] = useState(false)
  const [generateForm, setGenerateForm] = useState({ type: 'connect', expiry_days: '' })
  const [generated, setGenerated] = useState<GeneratedCard | null>(null)

  const loadCards = useCallback(async () => {
    try {
      const [i, a] = await Promise.all([
        get<{ cards: IssuedCard[] }>('/api/cards/issued'),
        get<{ cards: AcceptedCard[] }>('/api/cards/accepted'),
      ])
      setIssued(i.cards)
      setAccepted(a.cards)
    } catch {
      toast.error('Failed to load cards')
    }
  }, [])

  useEffect(() => { loadCards() }, [loadCards])

  async function handleGenerate() {
    try {
      const body: Record<string, unknown> = { type: generateForm.type }
      if (generateForm.expiry_days) {
        body.expiry_days = parseInt(generateForm.expiry_days, 10)
      }
      const result = await post<GeneratedCard>('/api/cards/generate', body)
      setGenerated(result)
      loadCards()
    } catch {
      toast.error('Failed to generate card')
    }
  }

  async function revokeIssued(cardKey: string) {
    try {
      await post(`/api/cards/issued/${encodeURIComponent(cardKey)}/revoke`)
      toast.success('Card revoked')
      loadCards()
    } catch {
      toast.error('Failed to revoke card')
    }
  }

  async function revokeAccepted(cardId: string) {
    try {
      await post(`/api/cards/accepted/${encodeURIComponent(cardId)}/revoke`)
      toast.success('Card revoked')
      loadCards()
    } catch {
      toast.error('Failed to revoke card')
    }
  }

  async function muteAccepted(cardId: string) {
    try {
      await post(`/api/cards/accepted/${encodeURIComponent(cardId)}/mute`)
      toast.success('Card muted')
      loadCards()
    } catch {
      toast.error('Failed to mute card')
    }
  }

  async function unmuteAccepted(cardId: string) {
    try {
      await post(`/api/cards/accepted/${encodeURIComponent(cardId)}/unmute`)
      toast.success('Card unmuted')
      loadCards()
    } catch {
      toast.error('Failed to unmute card')
    }
  }

  function copyToClipboard(text: string) {
    navigator.clipboard.writeText(text).then(
      () => toast.success('Copied to clipboard'),
      () => toast.error('Failed to copy'),
    )
  }

  function formatDate(d: string | null): string {
    if (!d) return '--'
    return new Date(d).toLocaleString()
  }

  const tabClass = (t: string) =>
    `px-4 py-2 text-sm font-medium rounded-md transition-colors ${
      tab === t
        ? 'bg-accent text-accent-foreground'
        : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground'
    }`

  return (
    <div className="flex-1 overflow-auto">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 py-6 sm:py-8 space-y-8">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold flex items-center gap-2">
            <Link2 className="h-5 w-5" /> Connections
          </h1>
          <Button variant="outline" size="sm" onClick={() => { setShowGenerate(!showGenerate); setGenerated(null) }}>
            Generate Card
          </Button>
        </div>

        {/* Generate card form */}
        {showGenerate && !generated && (
          <div className="p-4 rounded-lg border border-border/40 bg-muted/30 space-y-3">
            <h2 className="text-sm font-medium">Generate Contact Card</h2>
            <div className="grid grid-cols-2 gap-3">
              <select
                className="px-3 py-2 text-sm rounded border border-border/40 bg-background"
                value={generateForm.type}
                onChange={(e) => setGenerateForm({ ...generateForm, type: e.target.value })}
              >
                <option value="connect">Connect</option>
                <option value="subscribe">Subscribe</option>
                <option value="invite">Invite</option>
              </select>
              <input
                className="px-3 py-2 text-sm rounded border border-border/40 bg-background"
                placeholder="Expiry (days, optional)"
                type="number"
                min="1"
                value={generateForm.expiry_days}
                onChange={(e) => setGenerateForm({ ...generateForm, expiry_days: e.target.value })}
              />
            </div>
            <div className="flex gap-2">
              <Button size="sm" onClick={handleGenerate}>Generate</Button>
              <Button variant="ghost" size="sm" onClick={() => setShowGenerate(false)}>Cancel</Button>
            </div>
          </div>
        )}

        {/* Generated card display */}
        {generated && (
          <div className="p-4 rounded-lg border border-border/40 bg-muted/30 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-medium">Card Generated</h2>
              <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => { setGenerated(null); setShowGenerate(false) }}>
                <X className="h-4 w-4" />
              </Button>
            </div>
            <div className="space-y-2">
              <label className="text-xs text-muted-foreground">YAML</label>
              <div className="relative">
                <pre className="p-3 rounded bg-background border border-border/40 text-xs overflow-x-auto whitespace-pre-wrap">{generated.yaml}</pre>
                <Button
                  variant="ghost" size="icon"
                  className="absolute top-2 right-2 h-6 w-6"
                  onClick={() => copyToClipboard(generated.yaml)}
                >
                  <Copy className="h-3 w-3" />
                </Button>
              </div>
            </div>
            <div className="space-y-2">
              <label className="text-xs text-muted-foreground">Compact String</label>
              <div className="relative">
                <pre className="p-3 rounded bg-background border border-border/40 text-xs overflow-x-auto break-all">{generated.compact}</pre>
                <Button
                  variant="ghost" size="icon"
                  className="absolute top-2 right-2 h-6 w-6"
                  onClick={() => copyToClipboard(generated.compact)}
                >
                  <Copy className="h-3 w-3" />
                </Button>
              </div>
            </div>
          </div>
        )}

        {/* Tabs */}
        <div className="flex gap-2">
          <button className={tabClass('issued')} onClick={() => setTab('issued')}>
            Issued Cards
          </button>
          <button className={tabClass('accepted')} onClick={() => setTab('accepted')}>
            Accepted Cards
          </button>
        </div>

        {/* Issued cards table */}
        {tab === 'issued' && (
          <div className="rounded-lg border border-border/40 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-muted/30 border-b border-border/40">
                  <th className="text-left px-4 py-2 font-medium text-muted-foreground">Type</th>
                  <th className="text-left px-4 py-2 font-medium text-muted-foreground">Issued To</th>
                  <th className="text-left px-4 py-2 font-medium text-muted-foreground">Status</th>
                  <th className="text-left px-4 py-2 font-medium text-muted-foreground">Created</th>
                  <th className="text-left px-4 py-2 font-medium text-muted-foreground">Last Used</th>
                  <th className="text-right px-4 py-2 font-medium text-muted-foreground">Actions</th>
                </tr>
              </thead>
              <tbody>
                {issued.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-4 py-8 text-center text-muted-foreground">
                      No issued cards yet.
                    </td>
                  </tr>
                )}
                {issued.map((card) => (
                  <tr key={card.card_key} className="border-b border-border/40 last:border-0">
                    <td className="px-4 py-2">
                      <span className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary">{card.card_type}</span>
                    </td>
                    <td className="px-4 py-2">{card.issued_to || '--'}</td>
                    <td className="px-4 py-2">
                      <span className={`text-xs px-2 py-0.5 rounded-full ${
                        card.status === 'active' ? 'bg-green-500/10 text-green-500' :
                        card.status === 'revoked' ? 'bg-red-500/10 text-red-500' :
                        'bg-muted text-muted-foreground'
                      }`}>{card.status}</span>
                    </td>
                    <td className="px-4 py-2 text-xs text-muted-foreground">
                      <span className="flex items-center gap-1">
                        <Clock className="h-3 w-3" />
                        {formatDate(card.created_at)}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-xs text-muted-foreground">{formatDate(card.last_used_at)}</td>
                    <td className="px-4 py-2 text-right">
                      {card.status === 'active' && (
                        <Button variant="ghost" size="sm" className="text-destructive hover:text-destructive" onClick={() => revokeIssued(card.card_key)}>
                          Revoke
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Accepted cards table */}
        {tab === 'accepted' && (
          <div className="rounded-lg border border-border/40 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-muted/30 border-b border-border/40">
                  <th className="text-left px-4 py-2 font-medium text-muted-foreground">Agent</th>
                  <th className="text-left px-4 py-2 font-medium text-muted-foreground">Type</th>
                  <th className="text-left px-4 py-2 font-medium text-muted-foreground">Host</th>
                  <th className="text-left px-4 py-2 font-medium text-muted-foreground">Status</th>
                  <th className="text-left px-4 py-2 font-medium text-muted-foreground">Last Connected</th>
                  <th className="text-right px-4 py-2 font-medium text-muted-foreground">Actions</th>
                </tr>
              </thead>
              <tbody>
                {accepted.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-4 py-8 text-center text-muted-foreground">
                      No accepted cards yet.
                    </td>
                  </tr>
                )}
                {accepted.map((card) => (
                  <tr key={card.card_id} className="border-b border-border/40 last:border-0">
                    <td className="px-4 py-2 font-medium">{card.agent_name}</td>
                    <td className="px-4 py-2">
                      <span className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary">{card.card_type}</span>
                    </td>
                    <td className="px-4 py-2 text-xs text-muted-foreground">{card.host || '--'}</td>
                    <td className="px-4 py-2">
                      <span className={`text-xs px-2 py-0.5 rounded-full ${
                        card.status === 'active' ? 'bg-green-500/10 text-green-500' :
                        card.status === 'muted' ? 'bg-yellow-500/10 text-yellow-500' :
                        card.status === 'revoked' ? 'bg-red-500/10 text-red-500' :
                        'bg-muted text-muted-foreground'
                      }`}>{card.status}</span>
                    </td>
                    <td className="px-4 py-2 text-xs text-muted-foreground">{formatDate(card.last_connected_at)}</td>
                    <td className="px-4 py-2 text-right space-x-1">
                      {card.status === 'active' && (
                        <>
                          <Button variant="ghost" size="sm" onClick={() => muteAccepted(card.card_id)}>
                            Mute
                          </Button>
                          <Button variant="ghost" size="sm" className="text-destructive hover:text-destructive" onClick={() => revokeAccepted(card.card_id)}>
                            Revoke
                          </Button>
                        </>
                      )}
                      {card.status === 'muted' && (
                        <>
                          <Button variant="ghost" size="sm" onClick={() => unmuteAccepted(card.card_id)}>
                            Unmute
                          </Button>
                          <Button variant="ghost" size="sm" className="text-destructive hover:text-destructive" onClick={() => revokeAccepted(card.card_id)}>
                            Revoke
                          </Button>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
