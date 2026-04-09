import { useCallback } from 'react'
import { useActivityData } from '@/hooks/useActivityData'
import { HeroSection } from '@/components/activity/HeroSection'
import { GoalsSection } from '@/components/activity/GoalsSection'
import { PlansSection } from '@/components/activity/PlansSection'
import { TodosSection } from '@/components/activity/TodosSection'
import { ActivityFeedSection } from '@/components/activity/ActivityFeedSection'

export default function ActivityPage() {
  const { state, budget, goals, plans, todos, errors, refresh } = useActivityData()

  const handleCompleteTodo = useCallback(
    async (id: string) => {
      try {
        await fetch(`/api/todos/${id}/complete`, { method: 'POST' })
        await refresh()
      } catch (e) {
        console.error('Failed to complete todo:', e)
      }
    },
    [refresh]
  )

  return (
    <div className="max-w-3xl mx-auto px-4 py-6">
      <div className="mb-6">
        <h1 className="text-xl font-semibold">Activity</h1>
        <p className="text-sm text-muted-foreground mt-1">
          What your agent is doing
        </p>
      </div>

      <HeroSection
        state={state}
        budget={budget}
        errors={{ state: errors.state, budget: errors.budget }}
      />

      <GoalsSection goals={goals} error={errors.goals} />
      <PlansSection plans={plans} error={errors.plans} />
      <TodosSection todos={todos} error={errors.todos} onComplete={handleCompleteTodo} />
      <ActivityFeedSection />
    </div>
  )
}
