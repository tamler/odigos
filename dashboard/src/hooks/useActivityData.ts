import { useEffect, useState, useCallback, useRef } from 'react'

export interface AgentState {
  current_phase: string | null
  current_activity: string | null
  current_plan: {
    id: string
    goal: string
    current_step: number
    total_steps: number
    conversation_id?: string
  } | null
}

export interface BudgetStatus {
  daily_spend: number
  monthly_spend: number
  daily_limit: number
  monthly_limit: number
  within_budget: boolean
  warning: boolean
  circuit_breaker?: boolean
  // Per-source spend today. Keys: 'llm', 'whisper', 'kie_image', 'kie_music', etc.
  // Empty when nothing has been recorded; backend always returns an object.
  by_source?: Record<string, number>
}

export interface Goal {
  id: string
  description: string
  progress: number
  status: string
  created_at: string
}

export interface ActivePlan {
  id: string
  goal: string
  current_step: number
  total_steps: number
  started_at: string
  conversation_id: string
}

export interface Todo {
  id: string
  description: string
  status: string
  scheduled_at: string | null
  goal_id: string | null
}

export interface ActivityData {
  state: AgentState | null
  budget: BudgetStatus | null
  goals: Goal[]
  plans: ActivePlan[]
  todos: Todo[]
  loading: boolean
  errors: { [source: string]: string | null }
}

const POLL_INTERVAL_MS = 15000

async function safeFetch<T>(url: string): Promise<{ data: T | null; error: string | null }> {
  try {
    const resp = await fetch(url)
    if (!resp.ok) {
      return { data: null, error: `HTTP ${resp.status}` }
    }
    const data = await resp.json()
    return { data, error: null }
  } catch (e) {
    return { data: null, error: e instanceof Error ? e.message : 'fetch failed' }
  }
}

export function useActivityData(): ActivityData & { refresh: () => Promise<void> } {
  const [state, setState] = useState<AgentState | null>(null)
  const [budget, setBudget] = useState<BudgetStatus | null>(null)
  const [goals, setGoals] = useState<Goal[]>([])
  const [plans, setPlans] = useState<ActivePlan[]>([])
  const [todos, setTodos] = useState<Todo[]>([])
  const [loading, setLoading] = useState(true)
  const [errors, setErrors] = useState<{ [k: string]: string | null }>({})
  const intervalRef = useRef<number | null>(null)

  const fetchAll = useCallback(async () => {
    const [stateRes, budgetRes, goalsRes, plansRes, todosRes] = await Promise.all([
      safeFetch<AgentState>('/api/state'),
      safeFetch<BudgetStatus>('/api/budget'),
      safeFetch<{ goals: Goal[] }>('/api/goals?status=active'),
      safeFetch<{ plans: ActivePlan[] }>('/api/plans/active'),
      safeFetch<{ todos: Todo[] }>('/api/todos?status=pending'),
    ])

    if (stateRes.data) setState(stateRes.data)
    if (budgetRes.data) setBudget(budgetRes.data)
    if (goalsRes.data) setGoals(goalsRes.data.goals)
    if (plansRes.data) setPlans(plansRes.data.plans)
    if (todosRes.data) setTodos(todosRes.data.todos)

    setErrors({
      state: stateRes.error,
      budget: budgetRes.error,
      goals: goalsRes.error,
      plans: plansRes.error,
      todos: todosRes.error,
    })
    setLoading(false)
  }, [])

  useEffect(() => {
    void fetchAll()

    const startPolling = () => {
      if (intervalRef.current) return
      intervalRef.current = window.setInterval(() => {
        void fetchAll()
      }, POLL_INTERVAL_MS)
    }

    const stopPolling = () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
    }

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        void fetchAll()
        startPolling()
      } else {
        stopPolling()
      }
    }

    if (document.visibilityState === 'visible') {
      startPolling()
    }

    document.addEventListener('visibilitychange', handleVisibilityChange)

    return () => {
      stopPolling()
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [fetchAll])

  return {
    state,
    budget,
    goals,
    plans,
    todos,
    loading,
    errors,
    refresh: fetchAll,
  }
}
