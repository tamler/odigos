import { useState, useEffect, useCallback } from 'react'
import { get } from '@/lib/api'
import { toast } from 'sonner'
import { Users, Wifi, WifiOff, Clock } from 'lucide-react'

interface Agent {
  agent_name: string
  role: string
  description: string
  specialty: string | null
  status: string
  last_seen: string | null
  evolution_score: number | null
  netbird_ip: string
}

export default function AgentsPage() {
  const [agents, setAgents] = useState<Agent[]>([])

  const loadAgents = useCallback(async () => {
    try {
      const data = await get<{ agents: Agent[] }>('/api/agents')
      setAgents(data.agents)
    } catch {
      toast.error('Failed to load agents')
    }
  }, [])

  useEffect(() => { loadAgents() }, [loadAgents])

  return (
    <div className="flex-1 overflow-auto">
      <div className="max-w-4xl mx-auto px-6 py-8 space-y-8">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold flex items-center gap-2">
            <Users className="h-5 w-5" /> Agent Network
          </h1>
        </div>

        {agents.length === 0 && (
          <div className="text-center py-16 text-muted-foreground">
            <Users className="h-8 w-8 mx-auto mb-3 opacity-50" />
            <p>No agents registered yet.</p>
            <p className="text-xs mt-1">Agents will appear here when they join the mesh.</p>
          </div>
        )}

        <div className="grid gap-4">
          {agents.map((a) => (
            <div key={a.agent_name} className="p-4 rounded-lg border border-border/40 bg-muted/30">
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{a.agent_name}</span>
                    <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">{a.role}</span>
                    {a.specialty && (
                      <span className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary">{a.specialty}</span>
                    )}
                  </div>
                  {a.description && <p className="text-sm text-muted-foreground mt-1">{a.description}</p>}
                </div>
                <div className="flex items-center gap-2">
                  {a.status === 'online' ? (
                    <Wifi className="h-4 w-4 text-green-500" />
                  ) : (
                    <WifiOff className="h-4 w-4 text-muted-foreground" />
                  )}
                  <span className="text-xs text-muted-foreground">{a.status}</span>
                </div>
              </div>
              <div className="flex gap-6 mt-3 text-xs text-muted-foreground">
                {a.netbird_ip && <span>IP: {a.netbird_ip}</span>}
                {a.evolution_score !== null && <span>Score: {a.evolution_score.toFixed(1)}</span>}
                {a.last_seen && (
                  <span className="flex items-center gap-1">
                    <Clock className="h-3 w-3" />
                    {new Date(a.last_seen).toLocaleString()}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
