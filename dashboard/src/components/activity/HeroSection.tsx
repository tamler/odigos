import { useNavigate } from 'react-router-dom'
import { DotMatrixLoader } from '@/components/ui/loader'
import { SegmentedProgressBar } from '@/components/ui/SegmentedProgressBar'
import type { AgentState, BudgetStatus } from '@/hooks/useActivityData'

interface HeroSectionProps {
  state: AgentState | null
  budget: BudgetStatus | null
  errors: { state: string | null; budget: string | null }
}

function WorkingNowCard({ state, error }: { state: AgentState | null; error: string | null }) {
  const navigate = useNavigate()

  if (error) {
    return (
      <div className="bg-card rounded-xl p-4 border border-border">
        <div className="text-[10px] font-semibold tracking-widest text-muted-foreground uppercase mb-2">
          Working Now
        </div>
        <div className="text-sm text-muted-foreground">Status unavailable</div>
      </div>
    )
  }

  const isActive = state?.current_phase || state?.current_plan
  const isPlanActive = !!state?.current_plan

  return (
    <div className="bg-card rounded-xl p-4 border border-border">
      <div className="text-[10px] font-semibold tracking-widest text-muted-foreground uppercase mb-2">
        Working Now
      </div>
      <div className="flex items-start gap-3">
        {isActive ? (
          <DotMatrixLoader size="md" />
        ) : (
          <div className="size-2 rounded-full bg-muted-foreground mt-1.5" />
        )}
        <div className="flex-1 min-w-0">
          {isPlanActive && state?.current_plan ? (
            <>
              <div className="text-sm font-medium">Executing plan</div>
              <div className="text-sm text-muted-foreground truncate">
                {state.current_plan.goal}
              </div>
              <div className="text-xs text-muted-foreground mt-1 tabular-nums">
                Step {state.current_plan.current_step} of {state.current_plan.total_steps}
              </div>
            </>
          ) : isActive ? (
            <>
              <div className="text-sm font-medium">
                {state?.current_phase?.replace(/_/g, ' ') || 'Thinking...'}
              </div>
              {state?.current_activity && (
                <div className="text-sm text-muted-foreground truncate">
                  {state.current_activity}
                </div>
              )}
            </>
          ) : (
            <div className="text-sm text-muted-foreground">Idle</div>
          )}
        </div>
      </div>
      {isPlanActive && state?.current_plan && (
        <div className="flex gap-2 mt-3">
          <button
            onClick={() => navigate(`/?c=${state.current_plan!.conversation_id}`)}
            className="text-xs text-primary hover:underline"
          >
            View plan →
          </button>
        </div>
      )}
    </div>
  )
}

function BudgetCard({ budget, error }: { budget: BudgetStatus | null; error: string | null }) {
  const navigate = useNavigate()

  if (error || !budget) return null

  return (
    <div
      className="bg-card rounded-xl p-4 border border-border cursor-pointer hover:border-primary/30 transition-colors"
      onClick={() => navigate('/settings#budget')}
    >
      <div className="text-[10px] font-semibold tracking-widest text-muted-foreground uppercase mb-2">
        Budget Today
      </div>
      <SegmentedProgressBar
        value={budget.daily_spend}
        max={budget.daily_limit}
        segments={10}
      />
      <div className="text-xs text-muted-foreground mt-2 tabular-nums">
        ${budget.daily_spend.toFixed(2)} / ${budget.daily_limit.toFixed(2)}
      </div>
      <div className="text-xs text-muted-foreground tabular-nums">
        Remaining: ${Math.max(0, budget.daily_limit - budget.daily_spend).toFixed(2)}
      </div>
    </div>
  )
}

export function HeroSection({ state, budget, errors }: HeroSectionProps) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-6">
      <WorkingNowCard state={state} error={errors.state} />
      <BudgetCard budget={budget} error={errors.budget} />
    </div>
  )
}
