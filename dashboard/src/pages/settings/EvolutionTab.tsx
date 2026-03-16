import { useState, useEffect, useCallback } from 'react'
import { get, post } from '@/lib/api'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Activity, TrendingUp, TrendingDown, AlertTriangle, Lightbulb, RotateCcw, Check } from 'lucide-react'

interface Trial {
  id: string
  hypothesis: string
  target: string
  status: string
  started_at: string
  expires_at: string
  evaluation_count: number
  min_evaluations: number
  avg_score: number | null
  baseline_avg_score: number | null
}

interface Evaluation {
  id: string
  task_type: string
  overall_score: number
  implicit_feedback: number
  created_at: string
}

interface Direction {
  id: string
  analysis: string
  direction: string
  confidence: number
  created_at: string
}

interface FailedTrial {
  id: string
  hypothesis: string
  failure_reason: string
  lessons: string
  created_at: string
}

interface Proposal {
  id: string
  role: string
  specialty: string
  description: string
  rationale: string
  status: string
  created_at: string
}

export default function EvolutionTab({ active }: { active?: boolean }) {
  const [activeTrial, setActiveTrial] = useState<Trial | null>(null)
  const [recentAvg, setRecentAvg] = useState<number | null>(null)
  const [evalCount, setEvalCount] = useState(0)
  const [evaluations, setEvaluations] = useState<Evaluation[]>([])
  const [directions, setDirections] = useState<Direction[]>([])
  const [failedTrials, setFailedTrials] = useState<FailedTrial[]>([])
  const [proposals, setProposals] = useState<Proposal[]>([])
  const [showFailed, setShowFailed] = useState(false)

  const loadAll = useCallback(async () => {
    try {
      const [status, evals, dirs, failed, props] = await Promise.all([
        get<{ active_trial: Trial | null; recent_eval_count: number; recent_avg_score: number | null }>('/api/evolution/status'),
        get<{ evaluations: Evaluation[] }>('/api/evolution/evaluations?limit=20'),
        get<{ directions: Direction[] }>('/api/evolution/directions?limit=5'),
        get<{ failed_trials: FailedTrial[] }>('/api/evolution/failed-trials?limit=10'),
        get<{ proposals: Proposal[] }>('/api/proposals?status=pending'),
      ])
      setActiveTrial(status.active_trial)
      setRecentAvg(status.recent_avg_score)
      setEvalCount(status.recent_eval_count)
      setEvaluations(evals.evaluations)
      setDirections(dirs.directions)
      setFailedTrials(failed.failed_trials)
      setProposals(props.proposals)
    } catch {
      toast.error('Failed to load evolution data')
    }
  }, [])

  useEffect(() => { loadAll() }, [loadAll])

  useEffect(() => { if (active) loadAll() }, [active])

  async function handlePromote(trialId: string) {
    try {
      await post(`/api/evolution/trial/${trialId}/promote`)
      toast.success('Trial promoted')
      loadAll()
    } catch {
      toast.error('Failed to promote trial')
    }
  }

  async function handleRevert(trialId: string) {
    try {
      await post(`/api/evolution/trial/${trialId}/revert`)
      toast.success('Trial reverted')
      loadAll()
    } catch {
      toast.error('Failed to revert trial')
    }
  }

  async function handleApproveProposal(id: string) {
    try {
      await post(`/api/proposals/${id}/approve`)
      toast.success('Proposal approved')
      loadAll()
    } catch {
      toast.error('Failed to approve proposal')
    }
  }

  async function handleDismissProposal(id: string) {
    try {
      await post(`/api/proposals/${id}/dismiss`)
      toast.success('Proposal dismissed')
      loadAll()
    } catch {
      toast.error('Failed to dismiss proposal')
    }
  }

  function scoreColor(score: number): string {
    if (score >= 8) return 'text-green-500'
    if (score >= 6) return 'text-yellow-500'
    return 'text-red-500'
  }

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 py-4 sm:py-6 space-y-5">
      {/* Overview stats */}
      <div className="grid grid-cols-3 gap-4">
        <div className="p-4 rounded-lg border border-border/40 bg-card">
          <div className="text-xs text-muted-foreground">Evaluations</div>
          <div className="text-2xl font-semibold mt-1">{evalCount}</div>
        </div>
        <div className="p-4 rounded-lg border border-border/40 bg-card">
          <div className="text-xs text-muted-foreground">Avg Score</div>
          <div className={`text-2xl font-semibold mt-1 ${recentAvg ? scoreColor(recentAvg) : ''}`}>
            {recentAvg ? recentAvg.toFixed(1) : '--'}
          </div>
        </div>
        <div className="p-4 rounded-lg border border-border/40 bg-card">
          <div className="text-xs text-muted-foreground">Trial Status</div>
          <div className="text-2xl font-semibold mt-1">
            {activeTrial ? 'Active' : 'None'}
          </div>
        </div>
      </div>

      {/* Active Trial */}
      {activeTrial && (
        <div className="p-4 rounded-lg border border-border/40 bg-card space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium flex items-center gap-2">
              <Activity className="h-4 w-4" /> Active Trial
            </h2>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={() => handlePromote(activeTrial.id)}>
                <Check className="h-3 w-3 mr-1" /> Promote
              </Button>
              <Button variant="outline" size="sm" onClick={() => handleRevert(activeTrial.id)}>
                <RotateCcw className="h-3 w-3 mr-1" /> Revert
              </Button>
            </div>
          </div>
          <p className="text-sm">{activeTrial.hypothesis}</p>
          <div className="grid grid-cols-3 gap-4 text-xs text-muted-foreground">
            <div>Evaluations: {activeTrial.evaluation_count}/{activeTrial.min_evaluations}</div>
            <div>Score: {activeTrial.avg_score?.toFixed(1) ?? '--'} vs baseline {activeTrial.baseline_avg_score?.toFixed(1) ?? '--'}</div>
            <div>Expires: {new Date(activeTrial.expires_at).toLocaleString()}</div>
          </div>
        </div>
      )}

      {/* Specialization Proposals */}
      {proposals.length > 0 && (
        <div className="space-y-3">
          <h2 className="text-sm font-medium flex items-center gap-2">
            <Lightbulb className="h-4 w-4" /> Specialization Proposals
          </h2>
          {proposals.map((p) => (
            <div key={p.id} className="p-4 rounded-lg border border-border/40 bg-card">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm font-medium">{p.role} {p.specialty && `(${p.specialty})`}</div>
                  <div className="text-xs text-muted-foreground mt-1">{p.description}</div>
                  {p.rationale && <div className="text-xs text-muted-foreground mt-1">Rationale: {p.rationale}</div>}
                </div>
                <div className="flex gap-2">
                  <Button variant="outline" size="sm" onClick={() => handleApproveProposal(p.id)}>Approve</Button>
                  <Button variant="ghost" size="sm" onClick={() => handleDismissProposal(p.id)}>Dismiss</Button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Direction Log */}
      {directions.length > 0 && (
        <div className="space-y-3">
          <h2 className="text-sm font-medium flex items-center gap-2">
            <TrendingUp className="h-4 w-4" /> Direction Log
          </h2>
          {directions.map((d) => (
            <div key={d.id} className="p-3 rounded-lg border border-border/40 bg-card text-sm">
              <div>{d.direction}</div>
              <div className="text-xs text-muted-foreground mt-1">
                {d.analysis} &middot; Confidence: {(d.confidence * 100).toFixed(0)}%
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Evaluation History */}
      <div className="space-y-3">
        <h2 className="text-sm font-medium">Recent Evaluations</h2>
        <div className="rounded-lg border border-border/40 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted/50">
              <tr>
                <th className="text-left px-3 py-2 text-xs text-muted-foreground font-medium">Type</th>
                <th className="text-left px-3 py-2 text-xs text-muted-foreground font-medium">Score</th>
                <th className="text-left px-3 py-2 text-xs text-muted-foreground font-medium">Feedback</th>
                <th className="text-left px-3 py-2 text-xs text-muted-foreground font-medium">Time</th>
              </tr>
            </thead>
            <tbody>
              {evaluations.map((e) => (
                <tr key={e.id} className="border-t border-border/20">
                  <td className="px-3 py-2">{e.task_type || '--'}</td>
                  <td className={`px-3 py-2 font-medium ${scoreColor(e.overall_score)}`}>{e.overall_score?.toFixed(1)}</td>
                  <td className="px-3 py-2">
                    {e.implicit_feedback > 0 ? <TrendingUp className="h-3 w-3 text-green-500 inline" /> :
                     e.implicit_feedback < 0 ? <TrendingDown className="h-3 w-3 text-red-500 inline" /> :
                     <span className="text-muted-foreground">--</span>}
                  </td>
                  <td className="px-3 py-2 text-muted-foreground">{new Date(e.created_at).toLocaleString()}</td>
                </tr>
              ))}
              {evaluations.length === 0 && (
                <tr><td colSpan={4} className="px-3 py-4 text-center text-muted-foreground">No evaluations yet</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Failed Trials */}
      {failedTrials.length > 0 && (
        <div className="space-y-3">
          <button
            onClick={() => setShowFailed(!showFailed)}
            className="text-sm font-medium flex items-center gap-2 text-muted-foreground hover:text-foreground transition-colors"
          >
            <AlertTriangle className="h-4 w-4" />
            Failed Trials ({failedTrials.length})
          </button>
          {showFailed && failedTrials.map((f) => (
            <div key={f.id} className="p-3 rounded-lg border border-border/40 bg-card text-sm">
              <div>{f.hypothesis}</div>
              <div className="text-xs text-muted-foreground mt-1">
                {f.failure_reason} &middot; {f.lessons}
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="h-4" />
    </div>
  )
}
