import { useState, useEffect, useCallback } from 'react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { ScrollArea } from '@/components/ui/scroll-area'
import { get } from '@/lib/api'
import { toast } from 'sonner'

interface Overview {
  total_queries_7d: number
  total_skill_uses_7d: number
  total_errors_7d: number
  active_plans: number
  user_profile_last_analyzed: string | null
}

interface Classification {
  classification: string
  count: number
  avg_score: number
  avg_duration: number
  avg_confidence: number
}

interface ClassificationsResponse {
  classifications: Classification[]
  total_queries: number
}

interface Skill {
  skill_name: string
  skill_type: string
  count: number
  avg_score: number
}

interface SkillsResponse {
  skills: Skill[]
  total_uses: number
}

interface ToolError {
  tool_name: string
  error_type: string
  count: number
  last_occurrence: string
}

interface ErrorsResponse {
  errors: ToolError[]
}

interface Plan {
  id: string
  conversation_id: string
  steps_total: number
  steps_done: number
  created_at: string
  updated_at: string
}

interface PlansResponse {
  plans: Plan[]
}

export default function AnalyticsPage() {
  const [overview, setOverview] = useState<Overview | null>(null)
  const [classifications, setClassifications] = useState<Classification[]>([])
  const [skills, setSkills] = useState<Skill[]>([])
  const [errors, setErrors] = useState<ToolError[]>([])
  const [plans, setPlans] = useState<Plan[]>([])
  const [loading, setLoading] = useState(true)

  const loadAll = useCallback(() => {
    setLoading(true)
    Promise.allSettled([
      get<Overview>('/api/analytics/overview'),
      get<ClassificationsResponse>('/api/analytics/classifications'),
      get<SkillsResponse>('/api/analytics/skills'),
      get<ErrorsResponse>('/api/analytics/errors'),
      get<PlansResponse>('/api/analytics/plans'),
    ]).then(([ov, cl, sk, er, pl]) => {
      if (ov.status === 'fulfilled') setOverview(ov.value)
      else toast.error('Failed to load overview')

      if (cl.status === 'fulfilled') setClassifications(cl.value.classifications)
      else toast.error('Failed to load classifications')

      if (sk.status === 'fulfilled') setSkills(sk.value.skills)
      else toast.error('Failed to load skills')

      if (er.status === 'fulfilled') setErrors(er.value.errors)
      else toast.error('Failed to load errors')

      if (pl.status === 'fulfilled') setPlans(pl.value.plans)
      else toast.error('Failed to load plans')

      setLoading(false)
    })
  }, [])

  useEffect(() => { loadAll() }, [loadAll])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
        Loading analytics...
      </div>
    )
  }

  return (
    <ScrollArea className="h-full">
      <div className="max-w-5xl mx-auto px-4 py-8 space-y-8">
        <h1 className="text-2xl font-semibold">Analytics</h1>

        {/* Section 1: Overview cards */}
        <section>
          <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wide mb-3">Last 7 days</h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <OverviewCard
              label="Queries"
              value={overview?.total_queries_7d ?? 0}
              description="Total queries handled"
            />
            <OverviewCard
              label="Skill Uses"
              value={overview?.total_skill_uses_7d ?? 0}
              description="Skills invoked"
            />
            <OverviewCard
              label="Errors"
              value={overview?.total_errors_7d ?? 0}
              description="Tool errors"
            />
            <OverviewCard
              label="Active Plans"
              value={overview?.active_plans ?? 0}
              description="Plans in progress"
            />
          </div>
        </section>

        {/* Section 2: Query Classifications */}
        <section>
          <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wide mb-3">Query Classifications</h2>
          <Card>
            <CardContent className="pt-4 overflow-x-auto">
              {classifications.length === 0 ? (
                <p className="text-sm text-muted-foreground">No classification data available.</p>
              ) : (
                <div className="min-w-[400px]">
                  <ResponsiveContainer width="100%" height={Math.max(classifications.length * 40, 120)}>
                    <BarChart data={classifications} layout="vertical" margin={{ top: 0, right: 16, left: 8, bottom: 0 }}>
                    <XAxis type="number" tick={{ fontSize: 12, fill: 'hsl(var(--muted-foreground))' }} />
                    <YAxis
                      type="category"
                      dataKey="classification"
                      width={140}
                      tick={{ fontSize: 12, fill: 'hsl(var(--muted-foreground))' }}
                    />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: 'hsl(var(--popover))',
                        border: '1px solid hsl(var(--border))',
                        borderRadius: '6px',
                        fontSize: '12px',
                        color: 'hsl(var(--popover-foreground))',
                      }}
                    />
                    <Bar dataKey="count" fill="hsl(var(--primary))" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
                </div>
              )}
            </CardContent>
          </Card>
        </section>

        {/* Section 3: Skill Usage */}
        <section>
          <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wide mb-3">Skill Usage</h2>
          <Card>
            <CardContent className="pt-4 overflow-x-auto">
              {skills.length === 0 ? (
                <p className="text-sm text-muted-foreground">No skill usage data available.</p>
              ) : (
                <div className="min-w-[400px]">
                  <ResponsiveContainer width="100%" height={220}>
                    <BarChart data={skills} margin={{ top: 0, right: 16, left: 8, bottom: 40 }}>
                    <XAxis
                      dataKey="skill_name"
                      tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }}
                      angle={-30}
                      textAnchor="end"
                      interval={0}
                    />
                    <YAxis tick={{ fontSize: 12, fill: 'hsl(var(--muted-foreground))' }} />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: 'hsl(var(--popover))',
                        border: '1px solid hsl(var(--border))',
                        borderRadius: '6px',
                        fontSize: '12px',
                        color: 'hsl(var(--popover-foreground))',
                      }}
                    />
                    <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                      {skills.map((skill, index) => (
                        <Cell
                          key={`cell-${index}`}
                          fill={skill.skill_type === 'code' ? 'hsl(var(--primary))' : 'hsl(var(--muted-foreground))'}
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
                </div>
              )}
            </CardContent>
          </Card>
        </section>

        {/* Section 4: Tool Errors */}
        <section>
          <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wide mb-3">Tool Errors</h2>
          <Card>
            <CardContent className="pt-4">
              {errors.length === 0 ? (
                <p className="text-sm text-muted-foreground">No errors in the last 7 days.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border/40">
                        <th className="text-left py-2 pr-4 font-medium text-muted-foreground">Tool</th>
                        <th className="text-left py-2 pr-4 font-medium text-muted-foreground">Error Type</th>
                        <th className="text-left py-2 pr-4 font-medium text-muted-foreground">Count</th>
                        <th className="text-left py-2 font-medium text-muted-foreground">Last Seen</th>
                      </tr>
                    </thead>
                    <tbody>
                      {errors.map((err, i) => (
                        <tr key={i} className="border-b border-border/20 last:border-0">
                          <td className="py-2 pr-4 font-mono text-xs">{err.tool_name}</td>
                          <td className="py-2 pr-4 text-muted-foreground">{err.error_type}</td>
                          <td className="py-2 pr-4">{err.count}</td>
                          <td className="py-2 text-muted-foreground text-xs">
                            {new Date(err.last_occurrence).toLocaleString(undefined, {
                              month: 'short',
                              day: 'numeric',
                              hour: '2-digit',
                              minute: '2-digit',
                            })}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>
        </section>

        {/* Section 5: Active Plans */}
        <section>
          <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wide mb-3">Active Plans</h2>
          {plans.length === 0 ? (
            <Card>
              <CardContent className="pt-4">
                <p className="text-sm text-muted-foreground">No active plans.</p>
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-3">
              {plans.map((plan) => {
                const pct = plan.steps_total > 0
                  ? Math.round((plan.steps_done / plan.steps_total) * 100)
                  : 0
                return (
                  <Card key={plan.id}>
                    <CardContent className="pt-4 pb-4">
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-sm font-mono text-muted-foreground truncate max-w-xs">
                          {plan.conversation_id.length > 20
                            ? `${plan.conversation_id.slice(0, 8)}...${plan.conversation_id.slice(-8)}`
                            : plan.conversation_id}
                        </span>
                        <span className="text-sm text-muted-foreground shrink-0 ml-4">
                          {plan.steps_done}/{plan.steps_total} steps
                        </span>
                      </div>
                      <div className="w-full bg-muted rounded-full h-2">
                        <div
                          className="bg-primary h-2 rounded-full transition-all"
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">{pct}% complete</div>
                    </CardContent>
                  </Card>
                )
              })}
            </div>
          )}
        </section>
      </div>
    </ScrollArea>
  )
}

function OverviewCard({ label, value, description }: { label: string; value: number; description: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium text-muted-foreground">{label}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="text-3xl font-bold">{value}</div>
        <p className="text-xs text-muted-foreground mt-1">{description}</p>
      </CardContent>
    </Card>
  )
}
