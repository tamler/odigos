# Self-Improvement Engine — Design Document

## Goal

Give Odigos the ability to evaluate its own performance, generate improvement hypotheses, test them as time-boxed trials, and automatically revert changes that don't work — creating an autonomous feedback loop where the agent gets measurably better over time. The system should be lean enough that the agent can improve the improvement system itself.

## Architecture

The self-improvement engine has four components that plug into the existing heartbeat loop:

```
Heartbeat Idle Phase
    |
    v
Evaluator (C.1 + C.2)          Strategist (Direction)
  - Reviews past actions          - Summarizes evaluation trends
  - Generates rubric per action   - Proposes improvement hypotheses
  - Scores against rubric         - Maintains direction log
    |                               |
    v                               v
EvolutionEngine (Trial Manager)
  - Creates trials from hypotheses
  - Applies changes as ephemeral overrides
  - Monitors active trials
  - Promotes or auto-reverts based on scores
    |
    v
CheckpointManager (Deadman Switch)
  - Known-good state lives on disk (permanent)
  - Trial changes live in DB only (ephemeral)
  - Crash/timeout/expiry = automatic revert to disk state
  - Promotion = write trial overrides to disk
```

## Core Safety Principle: Deadman Switch

Trial changes are **never written to disk**. They exist only as overrides in the database.

```
On every prompt assembly:
  1. Load known-good state from disk (personality, prompt sections, skills)
  2. Query DB for active trial overrides
  3. Merge: disk state + overrides = current working state
  4. If no active trial, or trial expired, or DB unreachable:
     → disk state is used as-is (known-good)

Promotion (trial proved better):
  → Write overrides to disk files
  → Update known-good checkpoint record
  → Delete trial overrides from DB

Any failure mode (crash, hang, corrupt DB, timeout):
  → Process restarts, loads from disk = known-good
  → No explicit revert action needed
```

This means the agent **cannot permanently damage itself** through experimentation. The worst case is a bad trial runs until its time cap expires, then vanishes.

## Signal Sources (Type D — All Signals, Implicit)

Every signal feeds the evaluation pipeline. No explicit user action required — signals are inferred from behavior:

### Implicit Feedback Inference

| Behavior | Signal | Strength | Detection |
|----------|--------|----------|-----------|
| User sends follow-up building on response | Positive | Strong | Next message references or extends response content |
| User says "thanks" / acknowledges | Positive | Medium | Sentiment/keyword detection on next message |
| User corrects: "no, I meant..." | Negative | Strong | Existing correction detection in Reflector |
| User rephrases same question | Negative | Medium | Semantic similarity between consecutive user messages |
| Conversation abandoned (no message 30+ min after response) | Negative | Weak | Timestamp gap analysis |
| User immediately starts new conversation | Negative | Weak | New conversation created within 2 min |
| Task completed naturally (tool calls succeeded, clean ending) | Positive | Medium | No max-turn hit, last message is assistant |
| Hit max tool turns without resolution | Negative | Strong | Executor reports max turns reached |

### Signal Aggregation

All signals for a message/response pair are collected into a composite score:

```python
def infer_feedback(message_id, conversation) -> float:
    """Return -1.0 to 1.0 based on implicit behavioral signals."""
    signals = []
    # Check what happened after this response
    next_msg = get_next_user_message(message_id, conversation)
    if next_msg is None:
        signals.append(("abandoned", -0.3))
    elif is_correction(next_msg):
        signals.append(("correction", -0.8))
    elif is_rephrase(next_msg, original_user_message):
        signals.append(("rephrase", -0.6))
    elif is_acknowledgment(next_msg):
        signals.append(("acknowledged", 0.5))
    else:
        signals.append(("continued", 0.3))
    # Check task outcome
    if hit_max_tool_turns:
        signals.append(("max_turns", -0.9))
    if all_tool_calls_succeeded:
        signals.append(("tools_ok", 0.2))
    return weighted_average(signals)
```

## The Evaluation Pipeline (C.1 + C.2)

### C.1: Rubric Generation

Given a past action (message + response + tool calls + outcome), the evaluator asks the LLM:

```
Here is an interaction I had:

User: {message}
My response: {response}
Tools used: {tool_calls}
Outcome: {success/failure/unknown}
Implicit feedback: {inferred signal and strength}

Generate a scoring rubric for this type of interaction.
Return JSON:
{
  "task_type": "code_generation|research|conversation|planning|...",
  "criteria": [
    {"name": "criterion_name", "weight": 0.0-1.0, "description": "what good looks like"}
  ],
  "notes": "any context about why these criteria matter"
}
```

Rubrics are cached by `task_type` — the system builds a library of rubrics over time, only generating new ones for novel task types.

### C.2: Scoring

The same or a subsequent LLM call applies the rubric:

```
Score this interaction against the rubric:

Rubric: {rubric from C.1}
Interaction: {full context}

Return JSON:
{
  "scores": [
    {"criterion": "name", "score": 0-10, "observation": "specific evidence"}
  ],
  "overall": 0-10,
  "improvement_signal": "what would have made this better" | null
}
```

### Cost Control

- C.1 + C.2 use the **fallback model** (cheaper/faster), not the primary model
- Rubric generation is amortized — once per task type, reused many times
- Scoring runs on 1-3 past actions per idle cycle (adaptive — more when truly idle)

## The Strategist (Direction + Future Potential)

The strategist is both backward-looking (what failed, what worked) and forward-looking (where should I be heading). It maintains a **direction log** — a persistent record of the agent's evolving understanding of where it should improve.

### Direction Log

```sql
direction_log:
  id TEXT PRIMARY KEY,
  analysis TEXT,            -- narrative: where am I now?
  direction TEXT,           -- where should I head?
  opportunities TEXT,       -- JSON: potential areas for growth
  hypotheses TEXT,          -- JSON: specific changes to try
  confidence REAL,          -- how sure am I about this direction?
  based_on_evaluations INTEGER,  -- how many evaluations informed this?
  created_at TEXT DEFAULT (datetime('now'))
```

The direction log is append-only. The agent can look back and see how its understanding of itself evolved over time. New entries don't delete old ones — the history itself is valuable.

### Strategist Prompt

Runs periodically (every ~6 hours or after N new evaluations):

```
Here is my self-improvement history:

Recent evaluation trends:
{aggregated scores by task_type, criterion, time}

Previous direction assessments:
{last 3 direction_log entries}

Failed trials (do not retry these):
{failed-trial log entries}

Successful trials:
{promoted trial records}

Active trials:
{current experiments in progress}

Consider:
1. What patterns do you see in my evaluations?
2. Is my current direction working, or should I pivot?
3. What opportunities exist that I haven't explored?
4. What specific change would have the highest expected impact?
5. Are there capability gaps I should develop skills for?
6. Where do I think I could be in 50 more evaluation cycles?

Return JSON:
{
  "analysis": "narrative summary of where I am and how I got here",
  "direction": "where I should focus next and why",
  "opportunities": [
    {"area": "description", "potential": "high|medium|low", "rationale": "why"}
  ],
  "hypotheses": [
    {
      "description": "what to change",
      "target": "personality|prompt_section|skill|correction",
      "rationale": "why this should help",
      "expected_impact": "what improvement looks like",
      "confidence": 0.0-1.0
    }
  ],
  "trajectory_note": "where I think I'm heading long-term"
}
```

The strategist output feeds the EvolutionEngine as candidate trials AND is stored in the direction log for future reference.

## Checkpoint & Trial System

### What Gets Checkpointed (Known-Good on Disk)

| Layer | Storage | Format |
|-------|---------|--------|
| **Personality** | `data/personality.yaml` | YAML |
| **Prompt sections** | `data/prompt_sections/*.md` | Markdown with YAML frontmatter |
| **Skills** | `skills/*.md` | Markdown with YAML frontmatter |

### Trial Overrides (Ephemeral in DB)

```sql
trial_overrides:
  id TEXT PRIMARY KEY,
  trial_id TEXT REFERENCES trials(id),
  target_type TEXT,       -- "personality" | "prompt_section" | "skill"
  target_name TEXT,       -- file name or section name
  override_content TEXT,  -- full replacement content
  created_at TEXT DEFAULT (datetime('now'))
```

### Checkpoint Record

```sql
checkpoints:
  id TEXT PRIMARY KEY,
  parent_id TEXT REFERENCES checkpoints(id),
  label TEXT,
  personality_snapshot TEXT,
  prompt_sections_snapshot TEXT,    -- JSON: {name → content}
  skills_snapshot TEXT,             -- JSON: {name → content}
  created_at TEXT DEFAULT (datetime('now'))
```

A new checkpoint is created when a trial is promoted (overrides written to disk). The checkpoint stores the state *before* promotion, so we can walk back the tree if needed.

### Trial Lifecycle

```sql
trials:
  id TEXT PRIMARY KEY,
  checkpoint_id TEXT REFERENCES checkpoints(id),  -- state before trial
  hypothesis TEXT,
  target TEXT,                         -- personality|prompt_section|skill
  change_description TEXT,
  status TEXT DEFAULT 'active',        -- active|promoted|reverted|expired
  started_at TEXT DEFAULT (datetime('now')),
  expires_at TEXT,                     -- deadman time cap
  min_evaluations INTEGER DEFAULT 5,
  evaluation_count INTEGER DEFAULT 0,
  avg_score REAL,
  baseline_avg_score REAL,
  result_notes TEXT,
  direction_log_id TEXT,               -- which direction assessment spawned this
  created_at TEXT DEFAULT (datetime('now'))
```

### Trial Flow

```
Strategist generates hypothesis
    |
    v
EvolutionEngine creates trial:
  1. Snapshot current disk state as checkpoint
  2. Write override content to trial_overrides table
  3. Set expires_at = now + time_cap (default 48h)
  4. Status = 'active'
    |
    v
On every prompt assembly (while trial active):
  CheckpointManager.get_working_state():
    disk_state = load from files
    overrides = query trial_overrides WHERE trial is active
    return merge(disk_state, overrides)
    |
    v
Evaluator scores interactions during trial:
  evaluation_count++, update avg_score
    |
    v
Trial resolution (checked each heartbeat):
  IF evaluation_count >= min_evaluations:
    IF avg_score >= baseline + 0.5 → PROMOTE
    IF avg_score <= baseline - 0.3 → REVERT (early)
  IF now >= expires_at → EXPIRE (revert)
    |
    ├── PROMOTE:
    │   Write overrides to disk files
    │   Delete trial_overrides rows
    │   Update checkpoint as new known-good
    │   Log success
    │
    ├── REVERT / EXPIRE:
    │   Delete trial_overrides rows (disk unchanged)
    │   Log to failed_trials_log
    │   Status = 'reverted' or 'expired'
    │
    └── On crash/restart:
        trial_overrides still in DB but trial may be expired
        CheckpointManager checks expires_at before merging
        Expired overrides are ignored → disk state (known-good)
```

### Anti-Loop: Failed Trial Log

```sql
failed_trials_log:
  id TEXT PRIMARY KEY,
  trial_id TEXT REFERENCES trials(id),
  hypothesis TEXT,
  target TEXT,
  change_description TEXT,
  scores_summary TEXT,
  failure_reason TEXT,        -- "worse_than_baseline" | "inconclusive" | "expired"
  lessons TEXT,               -- LLM-generated: what to learn from this failure
  created_at TEXT DEFAULT (datetime('now'))
```

The strategist receives the full failed-trial log when generating new hypotheses. The prompt explicitly says: "These changes were already tried and failed. Do not retry them. Use them to inform better hypotheses."

## Dynamic Prompt Sections

The static sections in `prompt_builder.py` are replaced with evolvable markdown files.

### Section Files

```
data/prompt_sections/
  identity.md          -- who the agent is
  voice.md             -- communication guidelines
  task_patterns.md     -- learned patterns for common task types
  meta.md              -- self-improvement awareness and guidelines
```

Each section file:

```markdown
---
priority: 10
always_include: true
max_tokens: 500
---

# Identity

You are {name}, a personal AI agent...
```

- Loaded from disk on every request (hot-reload via mtime cache, same as personality today)
- Sorted by priority (lower = earlier in prompt)
- `always_include: false` sections only included when contextually relevant
- Individually versionable — a trial can modify one section without touching others
- The agent can create new section files through trials

### Prompt Assembly (Updated)

```python
def build_system_prompt(sections, memory_context, tool_context,
                        skill_catalog, corrections_context):
    parts = []
    for section in sorted(sections, key=lambda s: s.priority):
        if section.always_include or is_relevant(section, current_context):
            parts.append(section.content)
    parts.append(memory_context)
    parts.append(tool_context)
    parts.append(skill_catalog)
    parts.append(corrections_context)
    return "\n\n".join(filter(None, parts))
```

Note: personality.yaml fields (name, voice config) are used to seed the initial prompt section files. After migration, the prompt sections become the source of truth and personality.yaml becomes a legacy fallback.

## Integration with Existing Systems

### Heartbeat Phases (Updated)

```
Phase 1: Fire reminders          (existing)
Phase 2: Execute todos            (existing)
Phase 3: Deliver subagent results (existing)
Phase 4: Idle-think goals         (existing)
Phase 5: Self-improvement cycle   (NEW)
  5a. Score unreviewed past actions (C.1 + C.2, adaptive 1-5 per cycle)
  5b. Check active trials (promote/revert if ready)
  5c. Run strategist (if enough new evaluations since last run)
  5d. Create new trials from highest-confidence hypothesis
```

### Adaptive Scoring Cadence

```python
def actions_to_score_this_cycle(self) -> int:
    pending_todos = count_pending_todos()
    active_conversations = count_active_conversations()
    if pending_todos == 0 and active_conversations == 0:
        return 5  # fully idle, score aggressively
    elif pending_todos <= 2:
        return 2  # light load
    else:
        return 1  # busy, minimal scoring
```

### ContextAssembler (Updated)

```python
def build(self, message, conversation_id):
    memories = self.memory_manager.recall(message)
    corrections = self.corrections_manager.relevant(message)
    skills = self.skill_registry.list()

    # Load prompt sections with trial overrides applied
    sections = self.checkpoint_manager.get_working_sections()

    return build_system_prompt(
        sections=sections,
        memory_context=memories,
        tool_context=self.tool_context,
        skill_catalog=skills,
        corrections_context=corrections,
    )
```

## Evaluations Storage

```sql
evaluations:
  id TEXT PRIMARY KEY,
  message_id TEXT,
  conversation_id TEXT,
  task_type TEXT,
  rubric TEXT,                   -- JSON rubric used
  scores TEXT,                   -- JSON scores array
  overall_score REAL,
  improvement_signal TEXT,
  implicit_feedback REAL,        -- -1.0 to 1.0 from behavioral inference
  trial_id TEXT,                 -- which trial was active (null if known-good)
  created_at TEXT DEFAULT (datetime('now'))
```

## Phase 1 MVP Scope

### Must Have

1. **Evaluator** (`evaluator.py`) — C.1 rubric generation + C.2 scoring + implicit feedback inference
2. **CheckpointManager** (`checkpoint.py`) — deadman switch, disk = known-good, DB = ephemeral overrides
3. **EvolutionEngine** (`evolution.py`) — trial lifecycle, promote/revert, failed-trial log, direction log
4. **Dynamic prompt sections** (`section_registry.py`) — markdown files, hot-loaded, trial-overridable
5. **Heartbeat Phase 5** — adaptive scoring + trial management
6. **Migration** (`015_evolution.sql`) — all new tables

### Defer to Phase 2

- Strategist with full direction evaluation (Phase 1 uses simpler: "given these scores, suggest one change")
- Tool preferences file (agent can express preferences via prompt sections)
- Rubric library/caching (regenerate initially, cache once patterns stabilize)
- Specialist agent spawning (emerges from the improvement system)
- Cross-instance sharing of improvements

### Phase 1 Keeps It Lean By

- Using existing `fallback_model` for all evaluation LLM calls
- Adaptive scoring (1-5 actions per idle cycle depending on load)
- One active trial at a time (no parallel experiments)
- Simple promote/revert thresholds (no statistical significance testing)
- Prompt sections as plain markdown files (no complex registry)
- Implicit feedback only (no UI changes)
- Building on existing heartbeat, goal_store, corrections, and personality infrastructure
- Deadman switch eliminates complex rollback code

## File Structure

```
odigos/core/
  evaluator.py          -- C.1 rubric + C.2 scoring + implicit feedback
  evolution.py          -- EvolutionEngine (trials + direction log)
  checkpoint.py         -- CheckpointManager (deadman switch + overrides)

odigos/personality/
  prompt_builder.py     -- Updated: load dynamic sections instead of static template
  section_registry.py   -- Load prompt section files, merge trial overrides

data/
  personality.yaml      -- Legacy fallback, seeds initial prompt sections
  prompt_sections/      -- Evolvable prompt sections (known-good on disk)
    identity.md
    voice.md
    task_patterns.md
    meta.md

migrations/
  015_evolution.sql     -- checkpoints, trials, trial_overrides, evaluations,
                           failed_trials_log, direction_log
```

## How the Agent Reads This Document

This document lives in `docs/plans/` and can be referenced by the agent through its document tool. The agent should understand:

1. It has an evolution system that versions its own state
2. Changes are experimental by default — trial overrides live in DB, not on disk
3. If anything goes wrong, disk state (known-good) is the automatic fallback
4. Failed experiments are logged and must inform future attempts
5. The direction log tracks where the agent thinks it should be heading
6. Self-improvement is a first-class goal, not a side effect
7. The improvement system itself can be improved through the same mechanism
