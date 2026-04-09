# Surrogate Skill Verifier + Two-Axis Prompt Evolution

**Date:** 2026-04-09
**Status:** Approved
**Group:** 1 (Agent Quality)

## Research References

- [HERA](https://arxiv.org/html/2604.00901v2) — Two-axis prompt evolution: operational rules (recent corrections) + behavioral principles (stable identity)
- [EvoSkills](https://arxiv.org/html/2604.01687v1) — Informationally isolated surrogate verifier, co-evolutionary skill improvement
- [ReVeal](https://arxiv.org/html/2506.11442v1) — Self-verification via edge-case-aware test synthesis, turn-aware reward separation
- [Mem^p](https://arxiv.org/html/2508.06433v2) — Procedural memory with Add/Remove/Update lifecycle, reflection-based revision

---

## Feature 1: Surrogate Skill Verifier

### Goal

Validate skill quality at creation time using an informationally isolated LLM session. The verifier sees only the skill's description and output artifacts — never the system prompt — preventing confirmation bias. Focuses on text skills first (the primary skill type used by Kimi K2, GLM 5+ deployments), with a generic interface that extends to code skills and code generation later.

### Verification Flow

```
Skill created/updated
    |
    v
SkillVerifier.verify(skill_name)
    |
    v
1. Generate 3-5 test scenarios from skill.description
   (isolated session -- never sees skill.system_prompt)
    |
    v
2. For each scenario:
   a. Activate skill via ContextAssembler (realistic prompt with
      personality sections, corrections, experiences -- not bare injection)
   b. Run scenario query through LLM -> get response
    |
    v
3. Evaluate responses (isolated session)
   - Synthesize quality assertions from description + scenario
   - Score each response (pass/fail per assertion + overall 0.0-1.0)
    |
    v
4. If score < 0.6:
   - Generate structured failure diagnostics
   - Return diagnostics to caller (agent or heartbeat)
    |
    v
5. If score >= 0.6:
   - Mark skill verified, store verification score
   - Skill proceeds through normal maturity lifecycle
```

### Module: `odigos/skills/verifier.py`

**Generic interface:**

```python
@dataclass
class VerificationResult:
    passed: bool
    overall_score: float                    # 0.0-1.0
    scenario_results: list[ScenarioResult]  # per-scenario detail
    diagnostics: str | None                 # structured failure diagnostics
    escalation_level: int

@dataclass
class ScenarioResult:
    scenario: str           # the test query
    response: str           # skill's response (truncated for storage)
    assertions: list[str]   # quality assertions checked
    passed: list[bool]      # per-assertion pass/fail
    score: float            # 0.0-1.0

class SkillVerifier:
    async def verify(
        self,
        task_description: str,
        output_artifacts: list[str],
        escalation_level: int = 0,
    ) -> VerificationResult:
        """Verify output quality against task description.

        Generic interface -- works for skills, code gen, or any task.
        task_description: what the output should accomplish
        output_artifacts: the actual outputs to evaluate
        escalation_level: 0=normal, 1+=stricter criteria
        """

    async def verify_skill(self, skill_name: str) -> VerificationResult:
        """Skill-specific wrapper. Generates scenarios, runs them
        through the skill, then calls verify() on the results."""
```

### Isolation Boundary

The verifier uses two separate LLM calls, neither of which sees the skill's system_prompt:

1. **Scenario generation call:** Receives skill name + description. Generates test queries + edge cases. Uses a dedicated prompt (`data/prompts/verification_scenarios.md`).
2. **Evaluation call:** Receives task description + scenario + response. Synthesizes assertions and scores. Uses a dedicated prompt (`data/prompts/verification_evaluate.md`).

The skill execution (step 2 in the flow) uses ContextAssembler to build a realistic prompt that includes all active personality sections (identity, voice, operational_rules, behavioral_principles, etc.) alongside the skill's system_prompt. This ensures the verifier catches conflicts where global instructions might break skill behavior. The execution's internal reasoning is never passed to the verifier.

### V2 Extensions

**Multi-turn trajectories:** Most text skills are single-turn (legal-draft, journal, songwriting). Multi-turn skills like agent-browser require trajectory replay with tool call simulation — a fundamentally different verification approach. Deferred to V2. The `ScenarioResult` can be extended with a `trajectory: list[dict]` field when needed.

### Escalation Loop

When a skill passes initial verification but accumulates poor real-world scores (tracked by maturity lifecycle), the verifier is re-invoked with `escalation_level += 1`. Higher escalation levels instruct the scenario generator to:

- Generate harder, more ambiguous scenarios
- Include adversarial edge cases (contradictory requirements, missing context)
- Require stricter quality thresholds (0.7 at level 1, 0.8 at level 2)

Escalation is triggered during heartbeat Phase 6 when a committed skill's `avg_score` drops below its `verification_score - 0.15` (real-world performance diverging from verification). Limited to 1 re-verification per heartbeat cycle to avoid token bursts.

### New Skill Fields

```python
# Added to Skill dataclass in registry.py
verification_score: float   # 0.0-1.0 from last verification (default 0.0)
verification_at: str        # ISO timestamp of last verification (default "")
escalation_level: int       # 0=normal, 1+=tighter criteria (default 0)
```

The existing `verified: bool` field (currently code-skills only) extends to all skills. A skill is `verified=True` when `verification_score >= 0.6`.

### Maturity Gate

Update `maturity.py` to require verification for promotion and trigger demotion on failure:

- **progenitor -> committed:** requires `verified == True` (in addition to existing 5+ uses, 0.6+ score)
- **committed -> mature:** requires `verification_score >= 0.7` (in addition to existing 20+ uses, 0.75+ score)
- **Demotion on failed re-verification:** if a committed or mature skill fails re-verification (score < 0.5 after escalation), demote to progenitor. This prevents users from relying on a degraded skill.

### Integration Points

| Caller | When | Behavior |
|--------|------|----------|
| CreateSkillTool | Skill created | Run verification. If fails, return diagnostics to agent for revision. Skill still created (progenitor) but `verified=False`. |
| UpdateSkillTool | Skill updated | Re-run verification. Reset `verified` flag based on result. |
| Heartbeat Phase 6 | Periodic | Re-verify committed skills whose real-world score diverges from verification score. Escalate if needed. |
| Future: code tool | Code generated | Call `verify(task_description, [code_output])` directly. |

### Database

```sql
CREATE TABLE IF NOT EXISTS skill_verifications (
    id TEXT PRIMARY KEY,
    skill_name TEXT NOT NULL,
    scenarios_json TEXT,
    results_json TEXT,
    overall_score REAL,
    escalation_level INTEGER DEFAULT 0,
    diagnostics TEXT,
    model_used TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_skill_verifications_skill
    ON skill_verifications(skill_name);
```

### Prompts

Two new prompt files:

**`data/prompts/verification_scenarios.md`** — Instructs the LLM to generate test scenarios from a task description. Includes guidance on edge cases, ambiguity, and escalation levels.

**`data/prompts/verification_evaluate.md`** — Instructs the LLM to evaluate output against task description. Produces structured assertions, per-assertion pass/fail, overall score, and failure diagnostics.

### Cost

- 2 LLM calls per verification (scenario gen + evaluation), plus 3-5 skill execution calls (one per scenario)
- Defaults to the agent's own model for scenario gen and evaluation (quality judgment requires comparable reasoning). Config override: `verification_model`.
- Skill execution uses the agent's normal model
- Total cost per verification: roughly equivalent to one normal agent conversation turn
- Runs at creation time + periodic re-verification (not on every skill use)

---

## Feature 2: Two-Axis Prompt Evolution

### Goal

Periodically consolidate raw user corrections into two personality section files — operational rules (short-term concrete fixes) and behavioral principles (long-term identity patterns). Uses Mem^p's Add/Remove/Update lifecycle for principled merging. Corrections graduate from passive vector retrieval to active prompt directives.

### Two Axes

| Axis | Section File | Priority | Categories | Nature | Example |
|------|-------------|----------|------------|--------|---------|
| Operational | `data/agent/operational_rules.md` | 25 | accuracy, tool_choice | Concrete "do X not Y" fixes, recent | "Always verify dates before comparison" |
| Behavioral | `data/agent/behavioral_principles.md` | 15 | tone, preference, behavior | Stable identity patterns, generalized | "Prefer concise responses; expand only when asked" |
| Knowledge | (not consolidated) | N/A | factual | Stays in vector RAG only | "Project deadline is Friday, not Thursday" |

Knowledge corrections are marked `consolidated_at = 'skipped'` so they don't re-enter the pipeline, but remain available via `CorrectionsManager.relevant()` vector search.

Priority 15 places behavioral principles right after identity (10), before voice (20). Priority 25 places operational rules after voice, before general capabilities.

### Consolidation Flow

```
Phase 6 (run_evolution) -- after rollup_domain_performance(), before strategist
    |
    v
1. Load unconsolidated corrections
   (WHERE consolidated_at IS NULL)
    |
    v
2. If < 3 unconsolidated corrections, skip
   (batch for efficiency, avoid thrashing)
    |
    v
3. LLM classifies each correction into axis:
   - operational: accuracy, tool_choice -> concrete "do X not Y"
   - behavioral: tone, preference, behavior -> identity patterns
   - knowledge: factual corrections -> EXCLUDED from consolidation,
     stays in vector RAG only (e.g., "deadline is Friday not Thursday")
    |
    v
4. For each axis with new corrections:
   a. Load current section file content
   b. LLM merges using Mem^p operations:
      - ADD: new rule not covered by existing content
      - UPDATE: existing rule revised by newer correction
      - REMOVE: existing rule contradicted by correction
      - KEEP: no change needed
   c. Write updated section file
    |
    v
5. Mark corrections as consolidated (set consolidated_at)
6. Log consolidation event to consolidation_log
    |
    v
7. If section exceeds 500 tokens, run compaction:
   - LLM merges overlapping rules
   - Removes rules subsumed by more general principles
   - Outputs compact set
```

### Module: `odigos/core/consolidation.py`

```python
@dataclass
class ConsolidationOp:
    op: str             # "ADD", "UPDATE", "REMOVE", "KEEP"
    rule: str           # the rule text
    old_rule: str | None  # for UPDATE: the rule being replaced
    reason: str | None    # for REMOVE: why
    source_correction_id: str | None

class PromptConsolidator:
    OPERATIONAL_PATH = "data/agent/operational_rules.md"
    BEHAVIORAL_PATH = "data/agent/behavioral_principles.md"
    MIN_BATCH_SIZE = 3
    MAX_SECTION_TOKENS = 300  # 300 per section, 600 total across both axes

    async def consolidate(self) -> dict:
        """Run one consolidation pass. Returns stats."""

    async def _classify_corrections(
        self, corrections: list[dict]
    ) -> dict[str, list[dict]]:
        """Classify corrections into operational/behavioral axis."""

    async def _merge_axis(
        self, axis: str, current_content: str, corrections: list[dict]
    ) -> tuple[str, list[ConsolidationOp]]:
        """Merge corrections into section using Add/Remove/Update ops."""

    async def _compact_if_needed(self, axis: str, content: str) -> str:
        """Compact section if over token limit."""
```

### Consolidation Prompt

The merge LLM call receives:

1. Current section content (all existing rules)
2. Batch of new corrections (category, context, original/correction text)
3. Instructions to produce structured operations

Output format:

```json
{
  "operations": [
    {
      "op": "ADD",
      "rule": "Always verify dates before comparison",
      "source_correction_id": "abc123"
    },
    {
      "op": "UPDATE",
      "old_rule": "Search with broad terms",
      "new_rule": "Search with broad terms first, narrow only after reviewing results",
      "source_correction_id": "def456"
    },
    {
      "op": "REMOVE",
      "rule": "Always use formal tone in emails",
      "reason": "User corrected to prefer casual tone"
    }
  ],
  "updated_section": "... full section content after applying operations ..."
}
```

Prompt file: `data/prompts/consolidation_merge.md`

### Contradiction Resolution

When a batch contains contradictory corrections (e.g., one says "be more formal" and another says "stay casual"), the merge prompt applies **recency-wins** — the most recent correction takes precedence. If the contradiction is significant (opposing rules with similar recency), the LLM flags it in the operations output with `"conflict": true` and the consolidation log records it. This allows audit review but doesn't block the pipeline.

The merge prompt explicitly instructs: "If two corrections in this batch contradict each other, apply the most recent one. If an incoming correction contradicts an existing rule, UPDATE or REMOVE the existing rule."

### Reflection-Based Revision

When a correction directly contradicts an existing rule, the merge prompt includes both the rule and the contradiction with full context. The LLM decides:

- **UPDATE** if the correction refines the rule (e.g., "use formal tone" -> "use formal tone only for external emails")
- **REMOVE** if the correction fully reverses the rule (e.g., "never use formal tone")

This prevents stale rules from persisting after preferences change.

### Compaction

Runs when a section exceeds `MAX_SECTION_TOKENS` (300). Dedicated prompt (`data/prompts/consolidation_compact.md`) instructs the LLM to:

- Merge overlapping rules into single statements
- Remove rules subsumed by more general principles
- Preserve specificity where it matters (tool-specific rules stay specific)
- Output a compact ruleset that fits within the token budget

### Section File Format

```markdown
---
priority: 25
always_include: true
---

## Operational Rules

Rules derived from recent corrections. These are concrete behavioral fixes.

- Always verify date entities before temporal comparison
- When searching, try broad terms first; narrow only after reviewing results
- Never translate technical documentation -- output has terminology issues
- Confirm before deleting files, even when the user seems certain
```

### Trial Integration

Since these are standard SectionRegistry files:

- Strategist can propose trial overrides to `operational_rules` or `behavioral_principles`
- A/B testing validates whether consolidated rules improve response quality
- Promoted trial overrides persist via CheckpointManager
- Consolidation writes to disk; trials override at runtime -- no conflict

### Belt and Suspenders

Raw correction vector retrieval (`CorrectionsManager.relevant()`) continues to run alongside consolidated sections. This catches:

- Recent corrections not yet consolidated (< 3 batch threshold or between heartbeat runs)
- Highly specific corrections that don't generalize into rules

Over time, as corrections get consolidated, the vector retrieval returns fewer results (consolidated corrections are already in the prompt). No explicit deduplication needed -- the LLM naturally avoids repeating guidance that's already in its system prompt.

### Database Changes

```sql
-- Add column to existing corrections table
ALTER TABLE corrections ADD COLUMN consolidated_at TEXT;

-- New audit table
CREATE TABLE IF NOT EXISTS consolidation_log (
    id TEXT PRIMARY KEY,
    axis TEXT NOT NULL,
    corrections_processed INTEGER,
    operations_json TEXT,
    rules_before INTEGER,
    rules_after INTEGER,
    compacted INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);
```

### Migration Cold Start

On first run after migration, deployments may have many existing corrections with `consolidated_at IS NULL`. To avoid an expensive initial consolidation pass, the first run limits to corrections from the last 30 days (ordered by recency). Older corrections are marked `consolidated_at = 'pre-migration'` and remain available via vector retrieval only.

### Heartbeat Integration

In `odigos/core/heartbeat/maintenance.py`, `run_evolution()` gains a consolidation step:

```python
async def run_evolution(hb):
    scored = await hb.evolution_engine.score_past_actions(limit=3)
    result = await hb.evolution_engine.check_active_trial()
    await hb.evolution_engine.rollup_domain_performance()

    # NEW: consolidate corrections into prompt sections
    if hb.consolidator:
        stats = await hb.consolidator.consolidate()
        if stats["corrections_processed"] > 0:
            log.info("consolidation", **stats)

    if hb.strategist:
        if await hb.strategist.should_run():
            analysis = await hb.strategist.analyze()
```

### Prompt

**`data/prompts/consolidation_merge.md`** — Instructs the LLM to classify corrections into axes and produce Add/Remove/Update operations. Includes examples of each operation type.

**`data/prompts/consolidation_compact.md`** — Instructs the LLM to compact an over-budget section while preserving signal.

### Cost

- 1-2 LLM calls per consolidation pass (classify + merge per axis)
- Runs only when 3+ unconsolidated corrections exist
- At typical correction rates (2-5/day), consolidation runs at most once per heartbeat cycle
- Uses cheapest available model (classification is a simple task; merge quality matters less than verification since results are auditable and the LLM produces structured ops)

---

## Feature Interactions

These two features are independent in implementation but have natural synergies:

1. **Skill verification can generate corrections.** When the verifier finds poor skill output and the agent revises, the revision flows through normal correction detection. Over time, patterns like "skills dealing with legal documents need jurisdiction context" consolidate into behavioral principles.

2. **Consolidated rules improve skill execution.** Behavioral principles and operational rules are personality sections loaded into every prompt, including skill-activated conversations. This especially benefits cheaper models (Kimi K2, GLM 5+) where baseline behavior needs more guidance.

No shared code, tables, or runtime state. Can be built and shipped independently.

---

## New Files Summary

| File | Type | Purpose |
|------|------|---------|
| `odigos/skills/verifier.py` | Module | SkillVerifier class |
| `odigos/core/consolidation.py` | Module | PromptConsolidator class |
| `data/prompts/verification_scenarios.md` | Prompt | Test scenario generation |
| `data/prompts/verification_evaluate.md` | Prompt | Output quality evaluation |
| `data/prompts/consolidation_merge.md` | Prompt | Correction classification + merge |
| `data/prompts/consolidation_compact.md` | Prompt | Section compaction |
| `data/agent/operational_rules.md` | Section | Consolidated operational rules (starts empty) |
| `data/agent/behavioral_principles.md` | Section | Consolidated behavioral principles (starts empty) |

## Modified Files Summary

| File | Change |
|------|--------|
| `odigos/skills/registry.py` | Add verification_score, verification_at, escalation_level fields |
| `odigos/skills/maturity.py` | Gate promotion on verification |
| `odigos/tools/skill_manage.py` | Call verifier after create/update |
| `odigos/core/heartbeat/maintenance.py` | Add consolidation step + periodic re-verification |
| `odigos/core/evolution.py` | Wire up consolidator |
| `schema.sql` | Add skill_verifications table, consolidation_log table, corrections.consolidated_at column |
| `migrations/` | Migration for new tables + column |
