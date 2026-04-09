import { useNavigate } from 'react-router-dom'
import { SegmentedProgressBar } from '@/components/ui/SegmentedProgressBar'
import type { Goal } from '@/hooks/useActivityData'

interface GoalsSectionProps {
  goals: Goal[]
  error: string | null
}

function isStaleGoal(goal: Goal): boolean {
  if (goal.progress > 0) return false
  const created = new Date(goal.created_at).getTime()
  const dayMs = 24 * 60 * 60 * 1000
  return Date.now() - created < dayMs
}

export function GoalsSection({ goals, error }: GoalsSectionProps) {
  const navigate = useNavigate()

  if (error) return null

  const handleAdd = () => {
    navigate('/?c=new&prefill=Create+a+new+goal:+')
  }

  return (
    <section className="mb-6">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-[10px] font-semibold tracking-widest text-muted-foreground uppercase">
          Goals
        </h2>
        <button
          onClick={handleAdd}
          className="text-xs text-muted-foreground hover:text-foreground"
          aria-label="Add new goal"
        >
          +
        </button>
      </div>
      {goals.length === 0 ? (
        <div className="text-sm text-muted-foreground">
          No active goals. Set one in chat.
        </div>
      ) : (
        <div className="space-y-2">
          {goals.map((goal) => {
            const stale = isStaleGoal(goal)
            return (
              <button
                key={goal.id}
                onClick={() => navigate(`/?c=new&about=goal:${goal.id}`)}
                className="w-full bg-card rounded-xl p-3 border border-border hover:border-primary/30 transition-colors text-left"
              >
                <div className="flex items-center gap-3">
                  {!stale && (
                    <div className="w-24 flex-shrink-0">
                      <SegmentedProgressBar
                        value={goal.progress}
                        max={100}
                        segments={10}
                        size="sm"
                      />
                    </div>
                  )}
                  <div className="flex-1 text-sm truncate">{goal.description}</div>
                  {!stale && (
                    <div className="text-xs text-muted-foreground tabular-nums">
                      {goal.progress}%
                    </div>
                  )}
                </div>
              </button>
            )
          })}
        </div>
      )}
    </section>
  )
}
