import { useNavigate } from 'react-router-dom'
import type { ActivePlan } from '@/hooks/useActivityData'

interface PlansSectionProps {
  plans: ActivePlan[]
  error: string | null
}

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime()
  const diffMs = Date.now() - then
  const minutes = Math.floor(diffMs / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

export function PlansSection({ plans, error }: PlansSectionProps) {
  const navigate = useNavigate()

  if (error) return null

  return (
    <section className="mb-6">
      <h2 className="text-[10px] font-semibold tracking-widest text-muted-foreground uppercase mb-3">
        Plans In Progress
      </h2>
      {plans.length === 0 ? (
        <div className="text-sm text-muted-foreground">No plans in progress.</div>
      ) : (
        <div className="space-y-2">
          {plans.map((plan) => (
            <button
              key={plan.id}
              onClick={() => navigate(`/?c=${plan.conversation_id}`)}
              className="w-full bg-card rounded-xl p-3 border border-border hover:border-primary/30 transition-colors text-left"
            >
              <div className="flex items-center justify-between gap-3">
                <div className="text-sm font-medium truncate flex-1">{plan.goal}</div>
                <div className="text-xs text-muted-foreground tabular-nums whitespace-nowrap">
                  step {plan.current_step} of {plan.total_steps}
                </div>
              </div>
              <div className="text-xs text-muted-foreground mt-1">
                started {relativeTime(plan.started_at)}
              </div>
            </button>
          ))}
        </div>
      )}
    </section>
  )
}
