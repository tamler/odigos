# XSkill: Experience Store Design

**Date:** 2026-04-04
**Status:** Approved
**Goal:** Make the agent learn from tool outcomes by surfacing relevant tactical lessons before tool execution, with a feedback loop that strengthens good lessons and prunes bad ones.

## Context

Odigos already has an `agent_experiences` table, an extraction pipeline (heartbeat/profiling.py), and basic context injection. But the current system has gaps:
- Experiences are dumped into context generically (10 most recent, regardless of relevance)
- `times_applied` counter is never incremented (broken feedback loop)
- No confidence adjustment based on real-world outcomes
- No pruning of stale or unhelpful experiences

This design closes those gaps without new tables, new LLM calls, or new infrastructure.

## Decisions

| Question | Decision | Rationale |
|----------|----------|-----------|
| Where to inject hints | System prompt (enhanced `_experiences()`) | Minimal change, uses existing infrastructure. Pre-execution injection (Approach B) roadmapped for later. |
| How to match experiences | Dynamic tool mapping from `query_log` + classifier output | Self-updating, zero LLM cost. Falls back to confidence-based retrieval when no history. |
| Feedback mechanism | Executor adjusts confidence + times_applied after every tool call | Coarse but effective. Success boosts, retryable failure erodes. |
| Pruning | 30-day stale removal + low-confidence (<0.2) cleanup | Prevents experience bloat. Runs in existing profiling heartbeat cycle. |

## Design

### 1. Smart Experience Retrieval

**Modified file:** `odigos/core/context.py`

Replace the existing `_experiences()` inner function with targeted retrieval.

**Dynamic tool mapping function:**

```python
async def _get_likely_tools(db, classification: str) -> list[str]:
    """Get tools historically used for this classification type."""
    rows = await db.fetch_all(
        "SELECT tools_used, COUNT(*) as cnt FROM query_log "
        "WHERE classification = ? AND tools_used IS NOT NULL AND tools_used != '' "
        "GROUP BY tools_used ORDER BY cnt DESC LIMIT 5",
        (classification,),
    )
    tools = set()
    for row in rows:
        raw = row["tools_used"]
        if raw.startswith("["):
            import json
            tools.update(json.loads(raw))
        else:
            tools.update(t.strip() for t in raw.split(",") if t.strip())
    return list(tools)
```

Self-updating: as new tools are used for a classification type, they automatically appear in future lookups. No static map to maintain.

**Fallback map** for fresh installs with no `query_log` history:

```python
_FALLBACK_TOOLS = {
    "simple": [],
    "standard": ["search_web", "search_documents"],
    "document_query": ["search_documents", "read_file"],
    "complex": ["search_web", "search_documents", "run_code"],
    "planning": ["decompose_query"],
    "code": ["run_code", "create_file"],
    "creative": ["generate_image", "generate_music"],
    "email": ["check_email", "send_email", "search_email"],
}
```

**Updated `_experiences()` function:**

```python
async def _experiences():
    if not self.db or skip_experiences:
        return ""

    # Get classification from the classifier output (available in build() scope)
    classification_type = classification.get("classification", "standard")

    # Dynamic lookup: which tools are used for this classification type?
    tool_names = await _get_likely_tools(self.db, classification_type)
    if not tool_names:
        tool_names = _FALLBACK_TOOLS.get(classification_type, [])
    if not tool_names:
        # Third-tier fallback: get tools by category from the registry
        # Maps classification to tool categories for broad matching
        _CLASS_CATEGORIES = {
            "standard": ["search"], "document_query": ["search", "analysis"],
            "complex": ["search", "code"], "creative": ["create", "media"],
            "email": ["communication"], "code": ["code"],
        }
        cats = _CLASS_CATEGORIES.get(classification_type, [])
        if cats and self.tool_registry:
            tool_names = [
                t.name for t in self.tool_registry.list()
                if t.category in cats
            ]

    if tool_names:
        placeholders = ",".join("?" * len(tool_names))
        exp_rows = await self.db.fetch_all(
            f"SELECT tool_name, lesson, success, confidence "
            f"FROM agent_experiences "
            f"WHERE tool_name IN ({placeholders}) "
            f"ORDER BY confidence DESC, updated_at DESC LIMIT 5",
            tool_names,
        )
    else:
        # No tool signal: show high-confidence + failure anti-patterns
        exp_rows = await self.db.fetch_all(
            "SELECT tool_name, lesson, success, confidence "
            "FROM agent_experiences "
            "WHERE confidence >= 0.7 OR success = 0 "
            "ORDER BY confidence DESC, updated_at DESC LIMIT 5"
        )

    if not exp_rows:
        return ""

    lines = ["## Tactical experience (learned from past interactions)"]
    for row in exp_rows:
        prefix = "Warning" if not row["success"] else "Tip"
        lines.append(f"- [{prefix}] {row['tool_name']}: {row['lesson']}")
    return "\n".join(lines)
```

Key changes from current:
- Tool-targeted retrieval via dynamic mapping + classifier output
- Ranked by confidence (higher = more reliable), then recency
- Reduced from 10 to 5 items (fewer but more relevant)
- Warning/Tip labels help the agent distinguish avoid-patterns from apply-patterns
- Fallback for fresh installs

### 2. Feedback Loop in Executor

**Modified file:** `odigos/core/executor.py`

After tool execution completes (both success and failure), update the experience store. Added in `_execute_tool`, after the result is processed and before returning.

```python
# After tool execution, update experience confidence
if self.db:
    now = datetime.now(timezone.utc).isoformat()
    if result and result.success:
        await self.db.execute(
            "UPDATE agent_experiences "
            "SET times_applied = times_applied + 1, "
            "    confidence = MIN(confidence + 0.05, 1.0), "
            "    updated_at = ? "
            "WHERE tool_name = ?",
            (now, tool_call.name),
        )
    elif result and not result.success and category not in ('input', 'permission'):
        # Only erode for retryable failures, not user errors
        await self.db.execute(
            "UPDATE agent_experiences "
            "SET confidence = MAX(confidence - 0.1, 0.0), "
            "    updated_at = ? "
            "WHERE tool_name = ? AND success = 1",
            (now, tool_call.name),
        )
```

Design choices:
- Success: +0.05 confidence (gradual reinforcement), increment `times_applied`
- Failure: -0.1 confidence (stronger signal — lesson didn't help), only for retryable failures
- Input/permission errors don't erode confidence (not the lesson's fault)
- Only erodes positive lessons (`success = 1`); failure anti-patterns (`success = 0`) keep their confidence when the tool fails again (that's confirmation, not contradiction)
- Wrapped in try/except (non-critical path, should never break tool execution)

### 3. Experience Pruning

**Modified file:** `odigos/core/heartbeat/profiling.py`

Add to the end of `extract_experiences()`, after new experiences are inserted:

```python
# Prune stale and low-confidence experiences
await hb.db.execute(
    "DELETE FROM agent_experiences "
    "WHERE (times_applied = 0 AND created_at < datetime('now', '-30 days')) "
    "OR confidence < 0.2"
)
```

Two pruning rules:
- **Stale:** Never applied in 30 days → the lesson was never relevant enough to surface
- **Low confidence:** Confidence decayed below 0.2 → the lesson was repeatedly unhelpful

Runs in the existing heartbeat profiling cycle (every 20 ticks, ~10 minutes). No new scheduled task needed.

## File Change Summary

| File | Change |
|------|--------|
| `odigos/core/context.py` | Add `_get_likely_tools()`, `_FALLBACK_TOOLS`, rewrite `_experiences()` |
| `odigos/core/executor.py` | Add post-execution experience feedback (confidence + times_applied) |
| `odigos/core/heartbeat/profiling.py` | Add pruning query at end of `extract_experiences()` |

## What This Does NOT Change

- `agent_experiences` table schema — no migration needed, all fields already exist
- Experience extraction pipeline — unchanged (profiling.py just adds pruning)
- Routing rules — `skip_experiences` flag still honored for simple queries
- System prompt structure — experiences section format stays the same (just better content)
- No new LLM calls — dynamic tool mapping is a SQL query
- No new tables or migrations

## Future — Phase 4b (Roadmap Only)

**Pre-execution injection (Approach B):**
The executor looks up experiences for the specific tool about to execute and injects as `_experience_hints` in the params dict. Tools can use these to modify behavior (e.g., search tool adds site filters based on past success patterns). Requires changes to executor + BaseTool interface.

**Embedding-based matching:**
For queries that don't map cleanly to a classification type, use vector similarity against experience `situation` fields via sqlite-vec. Higher precision at the cost of an embedding call per query.

**Experience consolidation:**
When multiple similar lessons accumulate for the same tool, the extraction pipeline merges them into a single higher-confidence lesson. Reduces context token usage.
