# Adaptive Intelligence v1 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a query classifier that categorizes incoming messages and adjusts the pipeline -- simple queries skip RAG, document queries use optimized search, all queries are logged.

**Architecture:** New QueryClassifier module with Tier 1 heuristics + Tier 2 background model. Classifier runs in Agent._run() before executor. QueryAnalysis flows through executor to context assembler. Query log table tracks everything.

**Tech Stack:** Python, SQLite, existing LLM provider for background model

**Spec:** `docs/superpowers/specs/2026-03-17-adaptive-intelligence-v1-design.md`

---

## Chunk 1: Classifier + Migration

### Task 1: Query classifier module

**Files:**
- Create: `odigos/core/classifier.py`
- Create: `data/prompts/classifier.md`
- Create: `tests/test_classifier.py`

The classifier has Tier 1 (heuristic) and Tier 2 (background model). It returns a QueryAnalysis dataclass.

Implementation:
- QueryAnalysis dataclass: classification, confidence, entities, search_queries, sub_questions, tier
- `_classify_heuristic(message)`: hardcoded rules, returns classification string or None
- `classify(message)`: runs heuristic first, falls back to background model
- Background model uses `data/prompts/classifier.md` template with `load_prompt()`
- Parses JSON response from background model, falls back to "standard" on failure

Tests (using real objects, no mocks):
- test_heuristic_simple: "hi" → simple
- test_heuristic_document: "search the document for X" → document_query
- test_heuristic_complex: "compare A and B step by step" → complex
- test_heuristic_uncertain: "what's the weather like in Paris" → None (Tier 2)
- test_heuristic_order: "hi, search the document" → document_query (not simple)
- test_query_analysis_dataclass: verify fields

### Task 2: Migration for query_log

**Files:**
- Create: `migrations/027_query_log.sql`

```sql
CREATE TABLE IF NOT EXISTS query_log (
    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT UNIQUE NOT NULL,
    conversation_id TEXT NOT NULL,
    message_id TEXT,
    classification TEXT NOT NULL,
    classifier_tier INTEGER DEFAULT 1,
    classifier_confidence REAL,
    entities TEXT,
    search_queries TEXT,
    sub_questions TEXT,
    tools_used TEXT,
    duration_ms INTEGER,
    evaluation_score REAL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_query_log_classification ON query_log(classification);
CREATE INDEX IF NOT EXISTS idx_query_log_created ON query_log(created_at);
```

---

## Chunk 2: Pipeline Integration

### Task 3: Context assembler adjustments

**Files:**
- Modify: `odigos/core/context.py`

Add `query_analysis` keyword-only parameter to `build()`:

```python
async def build(
    self,
    conversation_id: str,
    current_message: str,
    max_tokens: int = 0,
    *,
    query_analysis=None,
) -> list[dict]:
```

Use classification to adjust behavior:
- `simple`: skip `memory_manager.recall()`, skip document listing
- `document_query` with search_queries: pass optimized queries to `recall()` instead of raw message
- `complex` with sub_questions: append hints to system prompt
- `standard`/`planning`: normal behavior

### Task 4: Executor + Agent wiring

**Files:**
- Modify: `odigos/core/executor.py`
- Modify: `odigos/core/agent.py`
- Modify: `odigos/core/evaluator.py`
- Modify: `odigos/main.py`

**Executor changes:**
- Add `query_analysis` keyword-only param to `execute()`
- Forward to `context_assembler.build()`
- Add `tools_used: set[str]` accumulator: collect tool names from every turn's tool_calls
- After loop, insert/update query_log row with tools_used, duration_ms, message_id
- Need db reference (already available via context_assembler.db or pass directly)

**Agent changes:**
- Create classifier in `__init__` (needs provider for Tier 2)
- In `_run()`, call `await self.classifier.classify(message.content)` before executor
- Pass `query_analysis=analysis` to `executor.execute()`

**Evaluator changes:**
- After scoring, update query_log: `UPDATE query_log SET evaluation_score = ? WHERE message_id = ?`

**Main.py changes:**
- Create QueryClassifier with provider and db
- Pass to Agent constructor

---

## Chunk 3: Deploy

### Task 5: Test, build, deploy

- Run full test suite
- Push to GitHub
- Deploy to personal VPS
- Deploy to tester VPS
- Update README with adaptive intelligence mention
