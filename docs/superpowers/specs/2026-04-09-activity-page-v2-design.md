# Activity Page V2

**Date:** 2026-04-09
**Status:** Approved
**Group:** 3 (UI)

## Goal

Transform the current `ActivityPage` from a notification feed into an interactive hub that shows what the agent is doing right now, what it's trying to accomplish, what needs the user's attention, and what just happened. The page becomes a navigation hub — every section is clickable to drill into details elsewhere.

---

## Page Layout

```
+-------------------------------------------------------------+
| Activity                                                    |
| What your agent is doing                                    |
+-------------------------------------------------------------+
|  +---------------------------+  +-----------------------+  |
|  | WORKING NOW               |  | BUDGET TODAY          |  |
|  | dot-matrix loader         |  | segmented bar (10)    |  |
|  | "Executing plan"          |  | $0.42 / $1.00         |  |
|  | "Draft newsletter"        |  | remaining: $0.58      |  |
|  | step 3 of 5               |  |                       |  |
|  | [pause] [view plan]       |  | [view history]        |  |
|  +---------------------------+  +-----------------------+  |
+-------------------------------------------------------------+
| GOALS                                                  [+]  |
| segmented bar  Ship Group 3 UI features              70%   |
| segmented bar  Onboard 3 testers                     20%   |
| segmented bar  Launch hosted offering                 0%   |
+-------------------------------------------------------------+
| PLANS IN PROGRESS                                           |
| Newsletter draft  · step 3 of 5  · started 12m ago         |
| Code review       · step 1 of 3  · started just now        |
+-------------------------------------------------------------+
| TODOS                                            [view all] |
| [ ] Reply to Florence's email             · 2h overdue      |
| [ ] Review legal-draft skill update       · today           |
| [ ] Check deploy logs                     · tomorrow        |
+-------------------------------------------------------------+
| RECENT ACTIVITY                              [filter v]     |
| ~ FINDING       New entity: "Project Aurora"     12:34     |
| * SUGGESTION    Consider archiving stale skills  11:50     |
| + COMPLETED     Music generation: track-42.mp3   11:22     |
| [show all]                                                  |
+-------------------------------------------------------------+
```

**Layout rules:**
- Hero is two-column on desktop (>768px), single column on mobile
- All sections below hero are single column, full width
- Max width: `max-w-3xl` (wider than current 2xl to accommodate two-column hero)
- Section spacing: `space-y-6`
- Each section has a header with uppercase tracking-widest label, optional action button on right
- Empty state per section: muted single-line message

---

## Section: Hero — Working Now + Budget

### Working Now Card

Shows live agent state from `/api/state`.

**States:**
- **Idle** — gray dot indicator, "Idle" label, last activity timestamp
- **Thinking** — `dot-matrix` loader, "Thinking..." label, current task description if known
- **Executing plan** — `dot-matrix` loader, "Executing plan", plan name + step number, "View plan" button
- **Background phase** — small label, "Memory evolution" / "Experience extraction" / etc.

**Backend addition:** `/api/state` is extended to also return:
```typescript
{
  current_phase: string | null      // heartbeat phase if running
  current_plan: {
    id: string
    goal: string
    current_step: number
    total_steps: number
  } | null
  current_activity: string | null   // free-form description
}
```

**Heartbeat state reporting:** The `Heartbeat` class gains a `get_status() -> dict` method that returns `{current_phase, current_activity, current_plan}`. The orchestrator sets these as instance attributes when entering/exiting each phase. The `/api/state` endpoint accesses the singleton heartbeat via existing dependency injection and calls `get_status()`.

**State endpoint caching:** `/api/state` already does multiple heavy queries (active conversations, total messages, memory counts, trial status). To avoid making it slower:
- Cache the heavy aggregate counts for 60 seconds in-memory (`functools.lru_cache` with TTL via a small wrapper, or a simple dict + timestamp)
- The Working Now data (`current_phase`, `current_plan`, `current_activity`) is read live from the heartbeat singleton — never cached
- Budget data is read live from BudgetTracker — never cached

### Budget Card

Pulled from `/api/budget` (already exists). Uses `SegmentedProgressBar`:
- 10 segments, auto-toned (green → amber at 75% → red at 90%)
- Shows `$X / $Y` and `Remaining: $Z` in plain text below
- Click → navigates to `/settings#budget` (existing settings page, budget section)

### Error handling
- If `/api/state` fails: show "Status unavailable" with retry button
- If `/api/budget` fails: hide the budget card entirely
- All fetches independent — one failure doesn't cascade

---

## Section: Goals

Pulled from `/api/goals?status=active`.

**Each goal row:**
- `SegmentedProgressBar` (sm size, default tone, no inline label) on the left
- Goal title in middle (truncate at one line)
- Percentage on right (`tabular-nums`)
- Click row → opens chat with goal context: `/?c=new&about=goal:abc123`

**Header action:** `[+]` button → opens chat with `Create a new goal:` prefilled.

**Empty state:** "No active goals. Set one in chat."

**Backend gap:**
- Add `progress: int (0-100)` field to `goals` table (default 0)
- `GoalStore.create_goal` initializes `progress=0` explicitly
- `GoalStore.update_goal` adds `progress` to its allowed update fields
- Existing `update_goal` tool gains a `progress` argument; agent updates manually
- Goals with `progress == 0` AND `created_at < 24h ago` render without the bar (just title) to avoid wall-of-empty-bars
- Schema migration `007_goal_progress.sql` — `ALTER TABLE goals ADD COLUMN progress INTEGER DEFAULT 0`

---

## Section: Plans In Progress

Pulled from new endpoint `/api/plans/active`.

**Each plan row:**
- Plan goal (truncate)
- Step counter "step N of M"
- Relative time started ("just now", "12m ago", "2h ago")
- Click → opens plan detail dialog showing all steps with status

**Empty state:** "No plans in progress."

**Backend gap:** New endpoint at `odigos/api/plans.py`:
```python
@router.get("/plans/active")
async def list_active_plans(db: Database = Depends(get_db)):
    rows = await db.fetch_all(
        "SELECT id, goal, steps, conversation_id, created_at, updated_at "
        "FROM task_plans WHERE status = 'in_progress' "
        "ORDER BY updated_at DESC LIMIT 20"
    )
    return {
        "plans": [
            {
                "id": r["id"],
                "goal": r["goal"],
                "current_step": _count_done(r["steps"]) + 1,
                "total_steps": _count_total(r["steps"]),
                "started_at": r["created_at"],
                "updated_at": r["updated_at"],
                "conversation_id": r["conversation_id"],
            }
            for r in rows
        ]
    }
```

Helper functions parse the `steps` JSON to count done/total.

**Future optimization (deferred):** If active plan count grows large, add `completed_steps` and `total_steps` columns to `task_plans`, updated by the plan executor as it progresses. For V2, JSON parsing is fine — typical active plan count is < 5.

---

## Section: Todos

Pulled from `/api/todos?status=pending` (already exists).

**Each todo row:**
- Checkbox (clicking marks done — calls existing API)
- Title (truncate)
- Relative due time, color-coded:
  - Red text if overdue
  - Default if due today/future
- Click row (not the checkbox) → opens chat about the todo

**Sort order:** overdue first, then by `due_at` ascending.

**Limit:** show top 5 in section. `[view all →]` link if more exist — expands the section inline (no new route). Toggles to `[show less]` when expanded.

**Empty state:** "No pending todos. Add one in chat."

---

## Section: Recent Activity Feed

The existing notification feed extracted into its own section.

### What stays the same
- Notification cards with type badges (`finding`, `suggestion`, `status`, `alert`)
- Date grouping (Today / Yesterday / date)
- Filter (now in dropdown instead of chip bar)
- Mark-as-read on scroll (500ms IntersectionObserver)
- "Discuss" button → navigates to chat
- "View artifact" button → opens artifact dialog
- "Load more" pagination
- Read/unread opacity dimming

### What changes
- **Header:** "RECENT ACTIVITY" uppercase + filter dropdown moves to right side
- **Density:** Show 5 most recent by default, "[show all →]" link expands to full feed inline
- **Card padding:** `p-3` instead of `p-4` to match other sections
- **No standalone page wrapper** — section header instead of page title
- **Filter dropdown** instead of chip bar to save vertical space

### Component extraction
- `dashboard/src/components/activity/ActivityFeedSection.tsx` — owns feed logic, takes `notifications`, `onMarkRead`, `onDiscuss`, `onViewArtifact` as props
- Artifact dialog stays in this component (it's feed-specific)
- IntersectionObserver mark-as-read logic moves into the section component

---

## Data Hook + Polling

A single hook `useActivityData()` orchestrates all fetches in parallel every 15 seconds while the page is visible.

```typescript
// dashboard/src/hooks/useActivityData.ts
export function useActivityData() {
  const [data, setData] = useState<{
    state: AgentState | null
    budget: BudgetStatus | null
    goals: Goal[]
    plans: ActivePlan[]
    todos: Todo[]
    loading: boolean
    errors: { [source: string]: string | null }
  }>({...initial})

  // Fetch all sources in parallel via Promise.allSettled
  // Polling: 15s interval when document.visibilityState === 'visible'
  // Pause polling when tab hidden (visibilitychange listener)
  // Resume on visible
  // Clean up on unmount
}
```

**Notifications stay on the existing `notificationStore`** — already managed via global Zustand and refreshes via WebSocket message bus.

**Per-source error handling:** each fetch in its own try/catch. Sections hide themselves or show error state if their data is missing. One failing endpoint never breaks the page.

**Future upgrade (deferred):** WebSocket push instead of polling. Logged in roadmap Group 5. Extending the existing chat WebSocket with new message types is the path. Ship after V2 polling proves out the data contract.

---

## New Files Summary

| File | Type | Purpose |
|------|------|---------|
| `dashboard/src/components/activity/HeroSection.tsx` | Component | Working Now + Budget cards |
| `dashboard/src/components/activity/GoalsSection.tsx` | Component | Active goals with progress |
| `dashboard/src/components/activity/PlansSection.tsx` | Component | In-progress plans |
| `dashboard/src/components/activity/TodosSection.tsx` | Component | Pending todos with quick complete |
| `dashboard/src/components/activity/ActivityFeedSection.tsx` | Component | Notification feed (extracted) |
| `dashboard/src/hooks/useActivityData.ts` | Hook | Polling orchestrator for all sources |
| `odigos/api/plans.py` | Module | New endpoint: GET /api/plans/active |
| `migrations/007_goal_progress.sql` | Migration | Add progress column to goals |

## Modified Files Summary

| File | Change |
|------|--------|
| `dashboard/src/pages/ActivityPage.tsx` | REWRITTEN as thin layout (~80 lines) composing the sections |
| `odigos/api/state.py` | Extend /api/state response with current_phase, current_plan, current_activity |
| `odigos/api/goals.py` | Include progress field in goal response |
| `odigos/core/goal_store.py` | Handle progress field on read/write |
| `odigos/core/heartbeat/orchestrator.py` | Set current_phase on heartbeat instance as phases enter/exit |
| `schema.sql` | Add progress column to goals table |
| `odigos/main.py` (or wherever routers register) | Register new plans router |
