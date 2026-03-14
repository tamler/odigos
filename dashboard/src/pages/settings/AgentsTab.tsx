import { useState, useEffect, useCallback } from 'react'
import { get, post } from '@/lib/api'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Users, Wifi, WifiOff, Clock, Plus, Server } from 'lucide-react'

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

interface SpawnedAgent {
  id: string
  agent_name: string
  role: string
  description: string
  deploy_target: string
  status: string
  deployed_at: string | null
  created_at: string
}

interface DeployTarget {
  name: string
  host: string
  method: string
  status: string
}

export default function AgentsTab() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [spawned, setSpawned] = useState<SpawnedAgent[]>([])
  const [targets, setTargets] = useState<DeployTarget[]>([])
  const [showSpawnForm, setShowSpawnForm] = useState(false)
  const [spawnForm, setSpawnForm] = useState({
    agent_name: '', role: '', description: '', specialty: '', deploy_target: '',
  })

  const loadAll = useCallback(async () => {
    try {
      const [a, s, t] = await Promise.all([
        get<{ agents: Agent[] }>('/api/agents'),
        get<{ agents: SpawnedAgent[] }>('/api/agents/spawned'),
        get<{ targets: DeployTarget[] }>('/api/agents/deploy-targets'),
      ])
      setAgents(a.agents)
      setSpawned(s.agents)
      setTargets(t.targets)
    } catch {
      toast.error('Failed to load agent data')
    }
  }, [])

  useEffect(() => { loadAll() }, [loadAll])

  async function handleSpawn() {
    if (!spawnForm.agent_name || !spawnForm.role || !spawnForm.description) {
      toast.error('Name, role, and description are required')
      return
    }
    try {
      await post('/api/agents/spawn', spawnForm)
      toast.success(`Specialist ${spawnForm.agent_name} spawn initiated`)
      setShowSpawnForm(false)
      setSpawnForm({ agent_name: '', role: '', description: '', specialty: '', deploy_target: '' })
      loadAll()
    } catch {
      toast.error('Failed to spawn agent')
    }
  }

  return (
    <div className="max-w-3xl mx-auto px-6 py-6 space-y-5">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium flex items-center gap-2">
          <Users className="h-4 w-4" /> Agent Network
        </h2>
        <Button variant="outline" size="sm" onClick={() => setShowSpawnForm(!showSpawnForm)}>
          <Plus className="h-3 w-3 mr-1" /> Spawn Specialist
        </Button>
      </div>

      {/* Spawn form */}
      {showSpawnForm && (
        <div className="p-4 rounded-lg border border-border/40 bg-card space-y-3">
          <h3 className="text-sm font-medium">Create Specialist Agent</h3>
          <div className="grid grid-cols-2 gap-3">
            <input
              className="px-3 py-2 text-sm rounded-md border border-border/40 bg-muted/50"
              placeholder="Agent name"
              value={spawnForm.agent_name}
              onChange={(e) => setSpawnForm({ ...spawnForm, agent_name: e.target.value })}
            />
            <input
              className="px-3 py-2 text-sm rounded-md border border-border/40 bg-muted/50"
              placeholder="Role (e.g. backend_dev)"
              value={spawnForm.role}
              onChange={(e) => setSpawnForm({ ...spawnForm, role: e.target.value })}
            />
            <input
              className="px-3 py-2 text-sm rounded-md border border-border/40 bg-muted/50"
              placeholder="Specialty tag"
              value={spawnForm.specialty}
              onChange={(e) => setSpawnForm({ ...spawnForm, specialty: e.target.value })}
            />
            <select
              className="px-3 py-2 text-sm rounded-md border border-border/40 bg-muted/50"
              value={spawnForm.deploy_target}
              onChange={(e) => setSpawnForm({ ...spawnForm, deploy_target: e.target.value })}
            >
              <option value="">Deploy target...</option>
              {targets.map((t) => (
                <option key={t.name} value={t.name}>{t.name} ({t.host})</option>
              ))}
            </select>
          </div>
          <input
            className="w-full px-3 py-2 text-sm rounded-md border border-border/40 bg-muted/50"
            placeholder="Description (1-2 sentences)"
            value={spawnForm.description}
            onChange={(e) => setSpawnForm({ ...spawnForm, description: e.target.value })}
          />
          <div className="flex gap-2">
            <Button size="sm" onClick={handleSpawn}>Create</Button>
            <Button variant="ghost" size="sm" onClick={() => setShowSpawnForm(false)}>Cancel</Button>
          </div>
        </div>
      )}

      {/* Registered agents */}
      {agents.length === 0 && !spawned.length && (
        <div className="text-center py-12 text-muted-foreground">
          <Users className="h-8 w-8 mx-auto mb-3 opacity-50" />
          <p className="text-sm">No agents registered yet.</p>
          <p className="text-xs mt-1">Agents will appear here when they join the mesh.</p>
        </div>
      )}

      <div className="grid gap-3">
        {agents.map((a) => (
          <div key={a.agent_name} className="p-4 rounded-lg border border-border/40 bg-card">
            <div className="flex items-start justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-medium text-sm">{a.agent_name}</span>
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

      {/* Spawned agents */}
      {spawned.length > 0 && (
        <div className="space-y-3">
          <h2 className="text-sm font-medium flex items-center gap-2">
            <Server className="h-4 w-4" /> Spawned Specialists
          </h2>
          {spawned.map((s) => (
            <div key={s.id} className="p-3 rounded-lg border border-border/40 bg-card">
              <div className="flex items-center justify-between">
                <div>
                  <span className="font-medium text-sm">{s.agent_name}</span>
                  <span className="text-xs text-muted-foreground ml-2">{s.role}</span>
                </div>
                <span className={`text-xs px-2 py-0.5 rounded-full ${
                  s.status === 'running' ? 'bg-green-500/10 text-green-500' :
                  s.status === 'deploying' ? 'bg-yellow-500/10 text-yellow-500' :
                  'bg-muted text-muted-foreground'
                }`}>{s.status}</span>
              </div>
              <div className="text-xs text-muted-foreground mt-1">
                Target: {s.deploy_target} {s.deployed_at && `| Deployed: ${new Date(s.deployed_at).toLocaleString()}`}
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="h-4" />
    </div>
  )
}
