# Adaptive Intelligence v2 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add evolvable classification rules, similarity-based route suggestions from past queries, and strategist integration so the system improves its own routing over time.

**Architecture:** Move heuristic rules to an editable prompt section. Add query_log_vec table for similarity search. Strategist reads query_log stats to propose classification/routing trials.

**Tech Stack:** Python, SQLite, sqlite-vec, existing evolution engine

**Spec:** `docs/superpowers/specs/2026-03-17-adaptive-intelligence-design.md`
**Foundation:** v1 already deployed (classifier, context adjustments, query_log table)

---

## Chunk 1: Evolvable Rules + Similarity Detection

### Task 1: Evolvable classification rules

**Files:**
- Create: `data/agent/classification_rules.md`
- Modify: `odigos/core/classifier.py`

Move the hardcoded heuristic rules to an editable prompt section that the evolution engine can modify via trials.

The classifier reads `data/agent/classification_rules.md` via `load_prompt()`. The file contains keyword lists per classification. The classifier parses them at runtime instead of using hardcoded strings.

Format for `classification_rules.md`:
```yaml
---
priority: 5
always_include: false
---
```
Body:
```
[document_query]
in the document, in the file, in the pdf, from the document, across all, in all documents, search for, search the

[complex]
compare, difference between, step by step, walk me through, analyze, and also, additionally

[planning]
plan for, schedule, how should i, help me figure out, what steps, create a plan

[simple]
hi, hello, hey, thanks, bye, ok, yes, no
```

The classifier parses this format: `[category]` headers followed by comma-separated signal phrases. If the file doesn't exist or can't be parsed, falls back to the hardcoded rules.

### Task 2: Similarity detection migration + vector storage

**Files:**
- Create: `migrations/028_query_log_vec.sql`
- Modify: `odigos/core/classifier.py`

Migration:
```sql
CREATE VIRTUAL TABLE IF NOT EXISTS query_log_vec USING vec0(
    query_log_rowid INTEGER PRIMARY KEY,
    embedding FLOAT[768]
);
```

After classifying and logging a query, embed the user message and store in `query_log_vec`. Before classifying, search `query_log_vec` for similar past queries with good scores and include the result as a routing hint.

Add to QueryClassifier:
- `__init__` accepts optional `vector_memory` (for embedding)
- After classification, embed message and store in `query_log_vec`
- Before Tier 1, search `query_log_vec` for top 3 similar past queries where `evaluation_score > 0.7`
- If strong match (similarity > 0.85), return past classification + hint

The hint is advisory -- included in QueryAnalysis as a new field `similarity_hint: str | None`.

---

## Chunk 2: Strategist Integration + Deploy

### Task 3: Strategist reads query_log

**Files:**
- Modify: `odigos/core/strategist.py`
- Modify: `data/prompts/strategist.md`

Add a `_get_query_log_summary()` method to the Strategist that runs:
```sql
SELECT classification, COUNT(*) as count,
       AVG(evaluation_score) as avg_score,
       AVG(duration_ms) as avg_duration
FROM query_log
WHERE created_at > datetime('now', '-7 days')
AND evaluation_score IS NOT NULL
GROUP BY classification
```

Add `{query_log_summary}` placeholder to the strategist prompt template. Format the SQL results as readable text.

Call `_get_query_log_summary()` in `run()` alongside `_get_evaluation_summary()` and pass to the prompt.

The strategist can now propose trials like: "document_query classification scored 0.4 average -- try routing these through code sandbox more aggressively" by modifying `classification_rules.md` or the classifier prompt.

### Task 4: Test, build, deploy

- Full test suite
- Push, deploy to personal VPS and testers
