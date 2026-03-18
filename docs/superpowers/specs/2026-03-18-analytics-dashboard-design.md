# Analytics Dashboard Design (V1)

## Goal

Frontend visualization of existing analytics API endpoints. No backend changes needed -- all data is already served by `/api/analytics/*`.

## Architecture

Pure frontend feature. Install Recharts for charts, create AnalyticsPage with 5 sections reading from existing endpoints.

## Data Sources (existing)

| Endpoint | Returns |
|---|---|
| `GET /api/analytics/overview` | total_queries_7d, total_skill_uses_7d, total_errors_7d, active_plans |
| `GET /api/analytics/classifications` | classification, count, avg_score, avg_duration per classification |
| `GET /api/analytics/skills` | skill_name, skill_type, count, avg_score per skill |
| `GET /api/analytics/errors` | tool_name, error_type, count, last_occurrence per tool+error |
| `GET /api/analytics/plans` | plan id, steps_total, steps_done, completion % |

## Frontend: AnalyticsPage.tsx

### Overview cards
4 metric cards in a grid: Total Queries (7d), Skill Uses (7d), Errors (7d), Active Plans. Each shows the number prominently.

### Query classifications chart
Horizontal bar chart (Recharts BarChart) showing query count per classification type. Colors by classification. Shows avg_score as secondary metric.

### Skill usage chart
Bar chart of top skills by usage count. Distinguishes text vs code skill types by color.

### Tool errors table
Simple table grouped by tool_name showing error_type and count. No chart needed -- tables are clearer for error data.

### Active plans list
List of recent plans with title, step progress (X/Y done), and a progress bar. Links to conversation if available.

## Files

| File | Change |
|---|---|
| `dashboard/package.json` | Add recharts dependency |
| `dashboard/src/pages/AnalyticsPage.tsx` | New: analytics dashboard |
| `dashboard/src/App.tsx` | Add `/analytics` route |
| `dashboard/src/layouts/AppLayout.tsx` | Add analytics nav icon |

## Out of Scope (V1)

- Time range selector (hardcoded to 7 days, matches API)
- Token cost trends (requires new endpoint)
- Real-time updates (page refreshes on mount)
- Export/download data
- Custom date ranges
