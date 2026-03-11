# Self-Improvement Engine — Design Document

## Goal

Give Odigos the ability to evaluate its own performance, generate improvement hypotheses, test them as time-boxed trials, and revert changes that don't work — creating an autonomous feedback loop where the agent gets measurably better over time. The system should be lean enough that the agent can improve the improvement system itself.

## Architecture

The self-improvement engine has four components that plug into the existing heartbeat loop:

```
Heartbeat Idle Phase
    |
    v
Evaluator (C.1 + C.2)          Strategist (Direction)
  - Reviews past actions          - Summarizes evaluation trends
  - Generates rubric per action   - Proposes improvement hypotheses
  - Scores against rubric         - Considers failed trials
    |                               |
    v                               v
EvolutionEngine (Trial Manager)
  - Creates trials from hypotheses
  - Applies changes via CheckpointManager
  - Monitors active trials
  - Promotes or reverts based on scores
    |
    v
CheckpointManager (Versioning)
  - Snapshots agent state
  - Applies/reverts changes atomically
  - Maintains known-good baseline
```

## Signal Sources (Type D — All Signals)

Every signal feeds the evaluation pipeline:

| Signal | Source | Collection |
|--------|--------|------------|
| **User corrections** | Existing CorrectionsManager | Already stored per-conversation |
| **Explicit feedback** | Thumbs up/down on messages | New: `message_feedback` table |
| **Task completion** | Did tool calls succeed? Max turns hit? | New: track in `action_log` |
| **Conversation health** | Abandoned? Redo requested? Length vs resolution? | Derived from existing message/conversation data |
| **Self-evaluation** | C.1/C.2 rubric scoring | New: `evaluations` table |

## The Evaluation Pipeline (C.1 + C.2)

### C.1: Rubric Generation

Given a past action (message + response + tool calls + outcome), the evaluator asks the LLM:

```
Here is an interaction I had:

User: {message}
My response: {response}
Tools used: {tool_calls}
Outcome: {success/failure/unknown}
User signals: {corrections, feedback, or "none"}

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

## The Strategist (Direction Evaluation)

This is the forward-looking component. Periodically (less frequent than scoring — every ~6 hours or N evaluations), the strategist:

```
Here is a summary of my recent self-evaluations:

Evaluation trends:
{aggregated scores by task_type, criterion, time}

Failed trials:
{what was tried, why it failed, when}

Current improvement hypotheses in progress:
{active trials}

My current strengths and weaknesses appear to be:
{derived from scores}

Consider:
1. What patterns do you see?
2. What direction should I focus improvement efforts?
3. What specific change would you hypothesize would help most?
4. Are there capability gaps I should develop skills for?

Return JSON:
{
  "analysis": "narrative summary of where I am",
  "direction": "where I should focus next",
  "hypotheses": [
    {
      "description": "what to change",
      "target": "personality|prompt_section|tool_preference|skill|correction",
      "rationale": "why this should help",
      "expected_impact": "what improvement looks like",
      "confidence": 0.0-1.0
    }
  ]
}
```

The strategist output feeds the EvolutionEngine as candidate trials.

## Checkpoint & Reversion System

### What Gets Checkpointed

Agent state is composed of mutable layers:

| Layer | Storage | Versioning |
|-------|---------|------------|
| **Personality** | `data/personality.yaml` | Full file snapshot in DB |
| **Prompt sections** | `data/prompt_sections/*.md` (new) | Per-file snapshots |
| **Tool preferences** | `data/tool_preferences.json` (new) | Full file snapshot |
| **Active corrections** | `corrections` table | Delta (corrections added/removed) |
| **Skills** | `skills/*.md` files | Per-file checksums + content |

### Checkpoint Structure

```sql
-- A snapshot of agent state
checkpoints:
  id TEXT PRIMARY KEY,
  parent_id TEXT REFERENCES checkpoints(id),  -- tree structure
  label TEXT,                                  -- "known-good", "trial-xyz"
  is_known_good INTEGER DEFAULT 0,
  personality_snapshot TEXT,                    -- full YAML content
  prompt_sections_snapshot TEXT,                -- JSON map of section_name → content
  tool_preferences_snapshot TEXT,               -- full JSON content
  corrections_delta TEXT,                       -- JSON: {added: [...], removed: [...]}
  skills_snapshot TEXT,                         -- JSON: {name → {checksum, content}}
  created_at TEXT DEFAULT (datetime('now'))
```

### Trial Lifecycle

```sql
trials:
  id TEXT PRIMARY KEY,
  checkpoint_id TEXT REFERENCES checkpoints(id),      -- state BEFORE trial
  trial_checkpoint_id TEXT REFERENCES checkpoints(id), -- state WITH trial applied
  hypothesis TEXT,                                      -- what we're testing
  target TEXT,                                          -- personality|prompt_section|...
  change_description TEXT,                              -- human-readable diff
  status TEXT DEFAULT 'active',                         -- active|promoted|reverted|expired
  started_at TEXT DEFAULT (datetime('now')),
  expires_at TEXT,                                      -- time cap
  min_evaluations INTEGER DEFAULT 5,                    -- confidence gate
  evaluation_count INTEGER DEFAULT 0,
  avg_score REAL,
  baseline_avg_score REAL,                              -- score before trial
  result_notes TEXT,                                    -- why promoted/reverted
  created_at TEXT DEFAULT (datetime('now'))
```

### Reversion Flow

```
Trial expires or reaches min_evaluations
    |
    v
Compare avg_score vs baseline_avg_score
    |
    ├── Better (>= +0.5 threshold) → Promote
    │     - Trial checkpoint becomes new known-good
    │     - Log success in trial record
    │     - Strategist informed of what worked
    │
    ├── Worse (<= -0.3 threshold) → Early revert
    │     - Restore from parent checkpoint
    │     - Log failure + scores
    │     - Add to failed-trial log
    │     - Strategist informed of what failed and why
    │
    └── Neutral (within thresholds) → Expire at time cap
          - Revert (don't keep neutral changes — bias toward simplicity)
          - Log as inconclusive
```

### Anti-Loop: Failed Trial Log

```sql
failed_trials_log:
  id TEXT PRIMARY KEY,
  trial_id TEXT REFERENCES trials(id),
  hypothesis TEXT,
  target TEXT,
  change_description TEXT,
  scores_summary TEXT,           -- JSON of aggregated scores
  failure_reason TEXT,           -- "worse_than_baseline" | "inconclusive" | "expired"
  lessons TEXT,                  -- LLM-generated: what to learn from this failure
  created_at TEXT DEFAULT (datetime('now'))
```

The strategist receives the full failed-trial log when generating new hypotheses. The prompt explicitly says: "These changes were already tried and failed. Do not retry them. Use them to inform better hypotheses."

## Dynamic Prompt Sections

Currently the system prompt is built from a fixed template in `prompt_builder.py`. We replace the static sections with a dynamic section system:

### Section Registry

```
data/prompt_sections/
  identity.md          -- who the agent is (evolved from personality)
  voice.md             -- communication guidelines
  tool_guidelines.md   -- tool selection preferences
  task_patterns.md     -- learned patterns for common task types
  meta.md              -- self-improvement awareness
```

Each section is:
- A markdown file with YAML frontmatter (priority, always_include, max_tokens)
- Hot-loaded on every request (like personality today)
- Individually versionable and evolvable
- The agent can create new sections or modify existing ones through trials

### Prompt Assembly (Updated)

```python
def build_system_prompt(personality, sections, memory_context,
                        tool_context, skill_catalog, corrections_context):
    parts = []
    # Load all prompt sections, sorted by priority
    for section in sorted(sections, key=lambda s: s.priority):
        if section.always_include or is_relevant(section, current_context):
            parts.append(section.content)
    # Inject dynamic context
    parts.append(memory_context)
    parts.append(tool_context)
    parts.append(skill_catalog)
    parts.append(corrections_context)
    return "\n\n".join(filter(None, parts))
```

## Tool Preferences

A new JSON file the agent evolves:

```json
{
  "preferences": [
    {
      "task_pattern": "user asks for current information",
      "prefer": ["search", "scrape_web"],
      "avoid": ["code"],
      "reason": "web tools are better for current info than code execution"
    }
  ],
  "pruned_for_specialists": {}
}
```

Injected into the system prompt as a "Tool Guidelines" section. The agent can modify this through trials.

## Integration with Existing Systems

### Heartbeat Phases (Updated)

```
Phase 1: Fire reminders          (existing)
Phase 2: Execute todos            (existing)
Phase 3: Deliver subagent results (existing)
Phase 4: Idle-think goals         (existing)
Phase 5: Self-improvement cycle   (NEW)
  5a. Score unreviewed past actions (C.1 + C.2, 1-3 per cycle)
  5b. Check active trials (promote/revert if ready)
  5c. Run strategist (if enough new evaluations since last run)
  5d. Create new trials from strategist hypotheses
```

### ContextAssembler (Updated)

```python
def build(self, message, conversation_id):
    # Existing
    personality = self.personality_loader.load()
    memories = self.memory_manager.recall(message)
    corrections = self.corrections_manager.relevant(message)
    skills = self.skill_registry.list()

    # New
    prompt_sections = self.section_registry.load_all()
    tool_prefs = self.tool_pref_manager.load()

    return build_system_prompt(
        personality=personality,
        sections=prompt_sections,
        memory_context=memories,
        tool_context=format_tool_prefs(tool_prefs),
        skill_catalog=skills,
        corrections_context=corrections,
    )
```

### Message Feedback (New Signal)

Add to the WebSocket protocol:

```json
{"type": "feedback", "message_id": "...", "signal": "positive|negative"}
```

Frontend: Thumbs up/down on assistant messages (using existing `feedback-bar` prompt-kit component).

## Lean MVP Scope

The full system described above is the target. The **minimum viable version** that still enables self-improvement:

### Must Have (Phase 1)

1. **Evaluator** — C.1 rubric generation + C.2 scoring against past actions
2. **Checkpoint table** — snapshot/restore agent state
3. **Trial table** — track active experiments with time cap
4. **Failed-trial log** — prevent loops
5. **Heartbeat Phase 5** — score 1-3 actions per idle cycle, manage trials
6. **Dynamic prompt sections** — replace static prompt_builder sections with evolvable files
7. **Message feedback** — thumbs up/down in UI (simplest user signal)

### Defer to Phase 2

- Strategist (direction evaluation) — phase 1 uses simpler hypothesis generation from evaluation scores
- Tool preferences file — agent can already express preferences via prompt sections
- Rubric caching/library — regenerate each time initially
- Specialist agent creation — this emerges from the improvement system
- Cross-instance sharing of improvements

### Phase 1 Keeps It Lean By

- Using existing `fallback_model` for all evaluation LLM calls
- Scoring only 1-3 actions per idle cycle
- One active trial at a time (no parallel experiments)
- Simple promote/revert thresholds (no statistical significance)
- Prompt sections as plain markdown files (no complex registry)
- Building on existing heartbeat, goal_store, and corrections infrastructure

## File Structure

```
odigos/core/
  evaluator.py          -- C.1 rubric + C.2 scoring
  evolution.py          -- EvolutionEngine (trial management)
  checkpoint.py         -- CheckpointManager (snapshot/restore)

odigos/personality/
  prompt_builder.py     -- Updated: load dynamic sections
  section_registry.py   -- Load/manage prompt section files

data/
  personality.yaml      -- (existing, now versionable)
  prompt_sections/      -- (new) evolvable prompt sections
    identity.md
    voice.md
    meta.md

migrations/
  015_evolution.sql     -- checkpoints, trials, evaluations, failed_trials_log, message_feedback
```

## How the Agent Reads This Document

This document lives in `docs/plans/` and can be referenced by the agent through its document tool. The agent should understand:

1. It has an evolution system that versions its own state
2. Changes to personality, prompt sections, and skills are experimental until promoted
3. Failed experiments are logged and should inform future attempts
4. The known-good checkpoint is the safe fallback
5. Self-improvement is a first-class goal, not a side effect
