# Proactive Agent — Engine, Notifications, Brain

**Date:** 2026-04-08
**Status:** Approved
**Goal:** Make the agent proactively helpful — it initiates work, surfaces insights, and delivers results through a unified notification system. Replace the weak idle_think with a structured pipeline. Rename wiki → brain. Consolidate all notification paths into one system.

## Context

The agent responds but doesn't initiate. The heartbeat's idle_think only reviews active goals every 15 minutes and occasionally creates a todo. It doesn't scan conversations for implicit needs, research open questions, synthesize across knowledge, or surface insights. Meanwhile, notifications flow through 4 scattered paths (Notifier, MessageBus, direct websocket, heartbeat utils) with no persistence or feedback tracking.

## Design

### 1. Rename: wiki → brain

All references to "wiki" become "brain" throughout the codebase:

| Old | New |
|-----|-----|
| `data/wiki/` | `data/brain/` |
| `data/wiki/entities/` | `data/brain/entities/` |
| `data/wiki/topics/` | `data/brain/topics/` |
| `data/wiki/synthesis/` | `data/brain/synthesis/` |
| `data/wiki/conversations/` | `data/brain/conversations/` |
| `data/wiki/index.md` | `data/brain/index.md` |
| `data/wiki/log.md` | `data/brain/log.md` |
| `WikiWriter` class | `BrainWriter` class |
| `wiki_writer.py` | `brain_writer.py` |
| `wiki_reader.py` | `brain_reader.py` |
| `wiki_maintenance.py` | `brain_maintenance.py` |
| `pending_wiki_writes` table | `pending_brain_writes` table |
| `run_wiki_maintenance()` | `run_brain_maintenance()` |
| `run_wiki_lint()` | `run_brain_lint()` |

The agent's diary lives in `data/agent/diary.md` (not brain — the diary is agent self-knowledge, not compiled user knowledge).

**No migration.** Clean deploy — drop DB, fresh schema. No legacy wiki references in the codebase.

### 2. Proactive Engine Pipeline

A new heartbeat phase replacing idle_think. Four stages, each a separate function in `odigos/core/heartbeat/proactive.py`:

**Stage 1: Scan (no LLM, DB queries only)**

Signal sources run in parallel via `asyncio.gather`. Each returns a list of opportunity dicts:

```python
@dataclass
class Opportunity:
    source: str          # Which scanner found it
    title: str           # Short description
    context: str         # Why this is worth doing
    priority_hint: float # Scanner's rough estimate 0-1
    conversation_id: str | None  # Where it came from
```

Initial signal sources:
- `scan_brain_gaps` — entities with no summary, facts with no cross-references, PARK'd items whose revisit conditions may be met
- `scan_recent_conversations` — last 24h: topics mentioned but not explored, commitments made, questions the agent couldn't fully answer
- `scan_active_goals` — existing idle_think logic (active goals + progress review)
- `scan_failed_ideas` — diary entries tagged as failed/abandoned, check if conditions changed

Adding a new source = writing one function and adding it to the list. No pipeline changes needed.

**Stage 2: Prioritize (one cheap LLM call)**

1. Dedup by title similarity (Jaccard > 0.8)
2. Filter out topics the user thumbs-downed (read `notifications` table reactions)
3. Filter out topics the agent already worked on recently (read diary)
4. If more than 3 candidates, one cheap LLM call ranks by: user relevance, novelty, actionability
5. Select top 1 opportunity per cycle
6. If nothing passes filtering: log "nothing to do", skip execute/publish

Static-first prompt: the ranking instruction template is static (cached), the opportunity list is dynamic.

**Stage 3: Execute (headless agent pipeline, async)**

- Build a `UniversalMessage` with the opportunity as content, channel="proactive"
- Call `agent.handle_message(headless=True)` — headless agent pipeline with budget tracking
- **Runs as `asyncio.create_task()`** — does not block the heartbeat tick. Stages 1-2 (scan + prioritize) run synchronously in the tick; stages 3-4 (execute + publish) run as a detached background task.
- **Safe tools only:** Proactive execution uses a `PROACTIVE_SAFE_TOOLS` whitelist: `find_tools`, `search`, `scrape`, `lookup_fact`, `knowledge_lookup`, `check_plan`, `read_file`. No send/write/delete tools (no `send_email`, `create_file`, `update_plan`, `run_code`). The whitelist is configurable in config.yaml under `proactive.safe_tools`.
- Result is a string (the agent's findings/recommendations)

**Stage 4: Publish (BrainWriter + Notification System)**

- Write result via `BrainWriter.write_synthesis(title, content, source, context, conversation_id)`
- Persist + deliver via `Notification.notify(type="finding", title, body=summary, artifact_path=filepath)`
- Write diary entry via `BrainWriter.append_diary(summary_of_what_was_done, open_threads)`
- Log cycle to `data/brain/log.md`

**Budget controls:**
- Same `_over_budget` gate as current idle_think
- One opportunity per cycle max (configurable: `proactive.max_per_cycle: 1`)
- 15-minute minimum between cycles (configurable: `proactive.interval_seconds: 900`)
- Auto-pause after 3 consecutive thumbs-down (24 hours)
- Config toggle: `proactive.enabled: true` (default true)
- Config frequency: `proactive.max_cycles_per_hour: 4` (default)

**UI controls (settings page):**
- Toggle: "Proactive mode" on/off → writes `proactive.enabled`
- Slider: "Proactive frequency" low(1)/medium(4)/high(8) per hour → writes `proactive.max_cycles_per_hour`

### 3. Notification System

One system for all agent-to-user communication. Replaces the 4 scattered paths.

**New `notifications` table:**

```sql
CREATE TABLE IF NOT EXISTS notifications (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT,
    artifact_path TEXT,
    conversation_id TEXT,
    source TEXT,
    read INTEGER DEFAULT 0,
    reaction TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_notifications_created ON notifications(created_at);
CREATE INDEX IF NOT EXISTS idx_notifications_read ON notifications(read);
```

`type` values: `finding` (proactive research), `suggestion` (actionable recommendation), `status` (task completion), `alert` (system warning).

`reaction` values: `thumbs_up` (more of this), `not_relevant` (explicit negative — less of this), `dismiss` (neutral hide — just clearing the feed), NULL (no reaction yet).

`source` values: `brain_gaps`, `recent_conversations`, `active_goals`, `failed_ideas`, `background_task`, `system`.

**Upgraded Notifier:**

```python
class Notifier:
    async def notify(self, title: str, body: str, *,
                     type: str = "status",
                     artifact_path: str | None = None,
                     conversation_id: str | None = None,
                     source: str | None = None) -> str:
        """Persist notification + push to all channels. Returns notification ID."""
        # 1. INSERT into notifications table
        # 2. Push to all connected channels via channel_registry
        # 3. Send web push to subscribed devices
        # Returns the notification ID for tracking
```

**Who calls it (everything through one path):**

| Caller | Type | Old Path |
|--------|------|----------|
| Proactive engine publish | finding, suggestion | NEW |
| callbacks.py (background task done) | status | Was: direct broadcast + separate notifier |
| background.py (heartbeat poll done) | status | Was: direct broadcast + separate notifier |
| Budget warning | alert | Was: logger only |
| Auto-update available | alert | Was: logger only |

**Notification API (for future UI):**

```
GET /api/notifications?limit=20&unread_only=true
PATCH /api/notifications/{id}  {read: true, reaction: "thumbs_up"}
```

These endpoints are defined in this spec so the delivery surface spec (Phase 8f) has a clean contract.

### 4. BrainWriter as Single Write Interface

BrainWriter (renamed from WikiWriter) is the sole interface for creating files in `data/brain/` and `data/sources/`.

**Methods:**

| Method | What | Was |
|--------|------|-----|
| `write_entity_page()` | Full entity page | Existing (WikiWriter) |
| `write_topic_index()` | Type-level index | Existing (WikiWriter) |
| `write_index()` | Master index.md | Existing (WikiWriter) |
| `write_conversation_summary()` | Conversation archive | Existing (WikiWriter) |
| `append_log()` | Append to log.md | Existing (WikiWriter) |
| `write_synthesis()` | Proactive findings, research | **New** |
| `write_source()` | External content archive | **New** — absorbs source_archiver |
| `append_diary()` | Agent self-note | **New** |
| `should_graduate()` | Graduation check | Existing (WikiWriter) |

**write_synthesis() format:**

```markdown
---
type: finding
title: SQLite WAL Performance Under Load
source: brain_gaps
source_context: User mentioned WAL concerns in conversation about deploy
conversation_id: abc123
created_at: 2026-04-08T05:30:00Z
---

# SQLite WAL Performance Under Load

[Agent's research findings]

## Sources
- [SQLite WAL docs](data/sources/2026-04-08-sqlite-wal.md)
- Conversation: abc123
```

**write_source()** absorbs `source_archiver.archive_source()`. Same SHA-256 dedup, same frontmatter. The standalone `source_archiver.py` is removed; callers switch to `BrainWriter.write_source()`.

**Staging pattern:** `write_synthesis()` and `append_diary()` follow the same stage-then-commit pattern as entity writes: insert a row into `pending_brain_writes` (operation: `synthesis_created` or `diary_entry`), then brain_maintenance drains to disk. This prevents file corruption from concurrent writes during maintenance cycles.

**append_diary()** writes to `data/agent/diary.md`:

```markdown
## [2026-04-08T05:30:00Z] proactive_cycle
Researched SQLite WAL performance after user mentioned concerns.
Found: WAL handles concurrent reads well but writers block each other.
Open thread: user may want connection pooling guidance.
```

Diary entries about the same topic graduate to `data/agent/diary/{slug}.md` when they hit 3+ entries (same pattern as entity graduation).

### 5. Agent Diary (Self-Continuity)

The diary is the agent's working memory between proactive cycles. Read at the start of each scan phase (last 5 entries, ~500 tokens) so the agent knows:
- What it already researched (don't repeat)
- What's still open (threads to continue)
- What reactions came back (adjust behavior)

**Location:** `data/agent/diary.md` (recent entries) + `data/agent/diary/` (graduated topic files)

**Written by:** Proactive engine publish step, via `BrainWriter.append_diary()`

**Read by:** Proactive engine scan step, before gathering signals

**Graduation:** 3+ diary entries mentioning the same topic → graduate to `data/agent/diary/{topic-slug}.md` with full history. The main `diary.md` gets a pointer: `[Continued in diary/sqlite-wal-research.md]`

### 6. Feedback Loop

Reactions from the notifications table calibrate the proactive engine:

**Per-source scoring:**
- Each proactive output has a `source` tag (brain_gaps, recent_conversations, etc.)
- thumbs_up = +1, not_relevant = -1, dismiss = 0 (neutral — just hides, doesn't penalize)
- Sources with cumulative score < -2 are suppressed
- Scores decay: halve every 7 days (so a bad week doesn't permanently kill a scanner)

**Global controls:**
- 3+ consecutive not_relevant on ANY source → auto-pause all proactive work for 24 hours
- Config toggle: `proactive.enabled` (UI toggle in settings)
- Config frequency: `proactive.max_cycles_per_hour` (UI slider: low=1, medium=4, high=8)

## File Changes

| File | Change |
|------|--------|
| `odigos/memory/brain_writer.py` | **Renamed** from wiki_writer.py. Add write_synthesis(), write_source(), append_diary() |
| `odigos/memory/brain_reader.py` | **Renamed** from wiki_reader.py. Update all paths |
| `odigos/memory/source_archiver.py` | **Removed** — absorbed into BrainWriter.write_source() |
| `odigos/core/heartbeat/proactive.py` | **New** — 4-stage pipeline: scan, prioritize, execute, publish |
| `odigos/core/heartbeat/brain_maintenance.py` | **Renamed** from wiki_maintenance.py |
| `odigos/core/heartbeat/orchestrator.py` | Replace idle_think with proactive pipeline, update brain_maintenance refs |
| `odigos/core/heartbeat/idle.py` | **Removed** — replaced by proactive.py |
| `odigos/core/notifier.py` | Upgrade: persist to notifications table, return notification ID |
| `odigos/api/notifications.py` | **New** — GET /api/notifications, PATCH /api/notifications/{id} |
| `odigos/api/callbacks.py` | Switch to unified Notifier.notify() |
| `odigos/core/heartbeat/background.py` | Switch to unified Notifier.notify() |
| `odigos/bootstrap.py` | Create data/brain/ dirs, update BrainWriter refs, add proactive config |
| `odigos/db.py` | Update _maybe_rebuild_from_brain() path |
| `schema.sql` | Add notifications table, rename pending_wiki_writes → pending_brain_writes |
| `odigos/tools/scrape.py` | Switch source_archiver → BrainWriter.write_source() |
| `odigos/memory/ingester.py` | Switch source_archiver → BrainWriter.write_source() |
| `odigos/core/reflector.py` | Update pending_brain_writes table name |
| `odigos/config.py` | Add proactive config section (enabled, interval, max_cycles_per_hour) |

## What Doesn't Change

- Entity extraction pipeline (reflector → memory manager → pending writes → brain maintenance)
- Vector memory, FTS, cross-encoder retrieval
- Context assembly (build_planned)
- Tool registry, executor, classifier
- Streaming, MessageBus, channel adapters
- Frontend (UI changes are Phase 8f)

## What This Enables (Future — Phase 8f Delivery Surface)

- Notification feed/inbox in the dashboard
- Thumbs up/down reaction buttons on proactive outputs
- "Discuss" action that opens a new conversation with the artifact as context
- Badge on sidebar showing unread proactive findings
- Markdown editor for browsing/editing brain files
- Settings UI toggle and slider for proactive controls
- Graph view of entity relationships in the brain
