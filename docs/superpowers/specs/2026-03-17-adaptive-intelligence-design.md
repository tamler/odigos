# Adaptive Intelligence Design

## Goal

Integrated system for query classification, adaptive pipeline routing, usage tracking, and similarity-based learning. The agent classifies incoming queries, routes them through the appropriate pipeline, tracks what worked, and improves its routing over time through the existing evolution engine. Combines Query Classification, SAGE Phase 2 (usage tracking), and SAGE Phase 3 (similarity detection) into one cohesive design.

## Context

Currently every message goes through the same pipeline: full RAG, full context assembly, single LLM call. Simple greetings get the same treatment as complex multi-document analysis requests. This wastes compute on simple queries and under-serves complex ones.

The evolution engine (evaluator, strategist, trials, checkpoints) already provides the self-improvement loop. This design adds the signals it needs to improve query handling.

## Architecture Overview

```
User Message
    │
    ▼
┌─────────────────┐
│ Query Classifier │ ── Tier 1: Heuristic rules (evolvable prompt section)
│                  │ ── Tier 2: Background model (if heuristic returns uncertain)
└────────┬────────┘
         │ Classification + entities + search queries + sub-questions
         ▼
┌─────────────────┐
│ Similarity Check │ ── Search query_log for past similar queries with good scores
│                  │ ── Suggests route/tools that worked before
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Pipeline Router  │ ── Adjusts: RAG depth, doc loading, decomposition hints
│                  │ ── Rules in evolvable prompt section
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Agent Executor   │ ── Normal tool loop with enriched context
│                  │ ── decompose_query tool available for complex queries
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Usage Tracker    │ ── Logs classification, tools used, duration, route
│                  │ ── Evaluator links score back to the log entry
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Evolution Engine │ ── Strategist reads query_log + evaluations
│ (existing)       │ ── Proposes trials on classification/routing rules
└─────────────────┘
```

## Component 1: Query Classifier

New module `odigos/core/classifier.py`.

### Tier 1: Heuristic Rules

Pattern matching against an evolvable rules file `data/agent/classification_rules.md`:

```yaml
---
priority: 5
always_include: false
---
```

The body contains classification rules in a structured format the classifier parses:

```
# Query Classification Rules

## simple
- Single word messages
- Greetings: hi, hello, hey, thanks, bye
- Messages under 5 words with no question mark

## document_query
- References an uploaded document by name
- Contains "in the document", "in the file", "from the PDF"
- Contains "across all", "in all documents", "search for"

## complex
- Multiple questions in one message (contains "and also", "additionally")
- Requests comparison ("compare", "difference between")
- Contains "step by step", "walk me through"

## planning
- Future-oriented: "plan", "schedule", "how should I"
- Goal-setting: "I want to", "help me figure out"

## uncertain
- Everything else (triggers Tier 2 LLM classification)
```

The classifier parses these rules and applies them in order. First match wins. If no rule matches, returns `uncertain`.

**Evolvable:** This file is a prompt section in `data/agent/`. The evolution engine can propose trial changes: "Add rule: messages mentioning dates → planning." If conversations improve, promote.

### Tier 2: Background Model Classification

When Tier 1 returns `uncertain`, call the background model (free Gemini Flash or configured `background_model`) with a structured prompt:

```
Classify this user message and extract metadata.

Message: "{message}"

Respond in JSON:
{
  "classification": "simple|standard|document_query|complex|planning",
  "entities": ["entity1", "entity2"],
  "confidence": 0.0-1.0,
  "search_queries": ["optimized query 1", "optimized query 2"],
  "sub_questions": ["sub-question 1", "sub-question 2"]  // only if complex/planning
}
```

The classification prompt is also evolvable -- stored as `data/prompts/classifier.md` and subject to trial modifications.

**Cost:** Uses the background model (free or cheap). Adds ~200ms latency only for uncertain queries. Simple queries (Tier 1) add ~0ms.

### Classifier Output

```python
@dataclass
class QueryAnalysis:
    classification: str          # simple, standard, document_query, complex, planning
    confidence: float            # 0-1
    entities: list[str]          # extracted names, places, concepts
    search_queries: list[str]    # optimized RAG queries
    sub_questions: list[str]     # decomposed sub-questions (if complex)
    tier: int                    # 1 = heuristic, 2 = LLM
```

## Component 2: Pipeline Router

The `QueryAnalysis` flows into context assembly and the executor, adjusting the pipeline:

| Classification | RAG | Reranker | Doc Pre-load | Context Extras |
|---|---|---|---|---|
| `simple` | Skip | Skip | Skip | Minimal context |
| `standard` | Full | Yes | On demand | Normal context |
| `document_query` | Full (with optimized queries) | Yes | Pre-load all (<1MB) | Document listing |
| `complex` | Full (with optimized queries) | Yes | On demand | Sub-questions as hints, decompose_query tool emphasized |
| `planning` | Light | Skip | Skip | Goal context emphasized, decompose_query tool emphasized |

Routing rules are stored in `data/agent/routing_rules.md` -- another evolvable prompt section. The context assembler reads the classification and adjusts what it loads.

### Changes to Context Assembly

`ContextAssembler.build()` accepts a `QueryAnalysis` parameter:

- If `simple`: skip memory recall entirely, minimal system prompt
- If entities extracted: use entities for targeted entity graph lookup (existing `EntityResolver`)
- If search_queries provided: use those for RAG instead of raw user text
- If sub_questions provided: include them as hints in the system prompt ("Consider addressing these aspects: ...")
- If `document_query`: ensure document listing is included

### decompose_query Tool

New tool registered for all classifications but only suggested in complex/planning contexts:

```python
class DecomposeQueryTool(BaseTool):
    name = "decompose_query"
    description = "Break a complex question into simpler sub-questions for systematic analysis."

    async def execute(self, params: dict) -> ToolResult:
        # The sub-questions from Tier 2 are already available in context
        # This tool is for when the agent wants to decompose further
        # It returns structured sub-questions for the agent to address one by one
```

The agent decides whether to use it. The evolution engine tracks whether using it improves scores.

## Component 3: Usage Tracker

### Database Schema

New migration:

```sql
CREATE TABLE IF NOT EXISTS query_log (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    message_id TEXT,
    user_message TEXT NOT NULL,
    classification TEXT NOT NULL,
    classifier_tier INTEGER DEFAULT 1,
    classifier_confidence REAL,
    entities TEXT,                 -- JSON array
    search_queries TEXT,           -- JSON array
    sub_questions TEXT,            -- JSON array
    tools_used TEXT,               -- JSON array of tool names
    route_taken TEXT,              -- what pipeline config ran
    duration_ms INTEGER,
    evaluation_score REAL,         -- linked after evaluator runs
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_query_log_classification ON query_log(classification);
CREATE INDEX IF NOT EXISTS idx_query_log_conversation ON query_log(conversation_id);
```

### Logging Flow

1. **Before agent loop:** Classifier runs, `query_log` row inserted with classification, entities, search_queries, sub_questions
2. **After agent loop:** Executor updates the row with `tools_used`, `route_taken`, `duration_ms`
3. **After evaluation:** Evaluator links `evaluation_score` to the row

### Embedding for Similarity

The `user_message` field is also embedded (using the existing embedding model) and stored in a vector table for similarity search:

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS query_log_vec USING vec0(
    query_log_rowid INTEGER PRIMARY KEY,
    embedding FLOAT[768]
);
```

This uses the existing `sqlite-vec` infrastructure. Each query_log entry gets an embedding of the user message.

## Component 4: Similarity Detector

When a new message comes in, after classification but before routing:

1. Embed the user message (already happens for RAG)
2. Search `query_log_vec` for the top 3 similar past queries
3. Filter to those with `evaluation_score > 0.7` (good outcomes)
4. If a strong match exists (similarity > 0.85), extract the `classification`, `tools_used`, and `route_taken` from the matched entry
5. Include as a hint in the agent's context: "A similar question was answered successfully before using [tools]. Consider a similar approach."

This is a lightweight vector search -- same infrastructure as RAG, just against a different table. No new models, no new dependencies.

**Not forced routing** -- the hint is advisory. The agent and classifier still make the final decision. But over time, the similarity hints converge on what works.

## Component 5: Evolution Integration

The strategist gains a new data source: `query_log`. It can now analyze:

- "document_query classification with search_documents tool scored 0.9 average, but without code tool scored 0.4 → propose trial to always suggest code tools for document queries"
- "complex queries that were decomposed scored 0.8 vs 0.5 undecomposed → strengthen decomposition hints"
- "the heuristic misclassified 15% of short document questions as simple → propose new rule"

The strategist proposes trials that modify:
- `data/agent/classification_rules.md` -- heuristic rules
- `data/prompts/classifier.md` -- Tier 2 classification prompt
- `data/agent/routing_rules.md` -- pipeline routing rules

All through the existing trial/checkpoint/promote/revert mechanism. No new evolution machinery needed.

## Integration Details

These address specific wiring points identified during review:

### Classifier → Executor → Context Assembly

The classifier runs in `Agent._run()` BEFORE the executor is invoked. The `QueryAnalysis` is passed to `Executor.execute()` as a new parameter, which forwards it to `ContextAssembler.build()`. The executor is the conduit, not the owner.

```
Agent._run(message)
  → classifier.classify(message) → QueryAnalysis
  → executor.execute(message, conversation_id, query_analysis=analysis)
    → context_assembler.build(conversation_id, message, query_analysis=analysis)
```

### Evaluator Linkage

The `query_log.message_id` stores the **assistant** message ID (the response). The evaluator already scores by assistant message_id. After scoring, the evaluator updates query_log:

```sql
UPDATE query_log SET evaluation_score = ? WHERE message_id = ?
```

The executor sets `message_id` on the query_log row after the agent produces a response.

### Tools Used Accumulator

The executor adds a `tools_used: set[str]` accumulator to its tool loop. Each turn, tool call names are added to the set. After the loop completes, the set is serialized to JSON and written to query_log.

### Routing Rules Owner

The **classifier** reads `classification_rules.md` directly (not via the prompt builder pipeline). The **context assembler** reads `routing_rules.md` directly to determine pipeline configuration based on the classification. Both use `load_prompt()` from `odigos/core/prompt_loader.py` for consistent mtime-cached file reading.

### Similarity Vector Join

`query_log_vec` uses integer rowid. Add an `INTEGER` rowid alias to `query_log`:

```sql
CREATE TABLE IF NOT EXISTS query_log (
    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT UNIQUE NOT NULL,
    ...
);
```

The `query_log_vec.id` (integer) maps to `query_log.rowid`. Join: `query_log_vec.id = query_log.rowid`.

### Heuristic Rule Ordering

Rules in `classification_rules.md` are evaluated in document order but with **specificity priority**: `document_query` and `complex` rules are checked BEFORE `simple` rules. The classifier checks in this order: `document_query` → `complex` → `planning` → `simple` → `uncertain`. This prevents "hi, search the document" from matching `simple` before `document_query`.

### Strategist Prompt Update

Add `{query_log_summary}` placeholder to the strategist prompt (`data/prompts/strategist.md`). The strategist populates it via a new `_get_query_log_summary()` method that runs:

```sql
SELECT classification, COUNT(*) as count,
       AVG(evaluation_score) as avg_score,
       AVG(duration_ms) as avg_duration
FROM query_log
WHERE created_at > datetime('now', '-7 days')
AND evaluation_score IS NOT NULL
GROUP BY classification
```

This produces a summary like: "document_query: 15 queries, avg score 0.72, avg 1200ms. simple: 42 queries, avg score 0.91, avg 300ms." The strategist uses this to identify which routes need improvement.

### Context Assembler Routing

The context assembler reads `routing_rules.md` via `load_prompt("routing_rules.md", fallback="", base_dir="data/agent")`. This is separate from the `SectionRegistry` pipeline (which builds the system prompt). The routing rules file is configuration for the assembler, not a prompt section injected into the LLM context.

## Files Modified/Created

| File | Change |
|---|---|
| `migrations/027_query_log.sql` | New: query_log and query_log_vec tables |
| `odigos/core/classifier.py` | New: QueryClassifier with Tier 1/2 classification |
| `odigos/core/context.py` | Accept QueryAnalysis, adjust RAG/context based on classification |
| `odigos/core/executor.py` | Accept QueryAnalysis param, tools_used accumulator, log to query_log |
| `odigos/core/agent.py` | Run classifier before executor, pass QueryAnalysis |
| `odigos/core/evaluator.py` | Link evaluation_score back to query_log entry |
| `odigos/core/strategist.py` | Read query_log for routing improvement proposals |
| `odigos/tools/decompose.py` | New: DecomposeQueryTool |
| `odigos/main.py` | Wire classifier into message handling, register decompose tool |
| `data/agent/classification_rules.md` | New: evolvable heuristic rules |
| `data/agent/routing_rules.md` | New: evolvable routing rules |
| `data/prompts/classifier.md` | New: Tier 2 classification prompt template |
| `tests/test_classifier.py` | New: classifier tests |
| `tests/test_query_log.py` | New: usage tracking tests |
| `tests/test_similarity.py` | New: similarity detection tests |
| `data/prompts/strategist.md` | Add {query_log_summary} placeholder |

## Implementation Phases

While designed as one integrated system, implementation can proceed in phases:

**Phase A (Query Classifier + Router):** Classifier, routing rules, context adjustments. Immediate value: simple queries get faster, complex queries get richer context.

**Phase B (Usage Tracker):** query_log table, logging in executor/evaluator. Immediate value: visibility into what's happening per query.

**Phase C (Similarity Detector):** Vector embeddings of queries, similarity search, hints in context. Immediate value: the agent remembers what worked.

**Phase D (Evolution Wiring):** Strategist reads query_log, proposes trials on classifier/routing rules. Immediate value: the system improves itself.

Each phase produces working, testable software. Phases B-D depend on A. C depends on B. D depends on B.

## Performance Impact

- **Tier 1 classification:** <1ms (regex/string matching)
- **Tier 2 classification:** ~200ms (background model call, only for uncertain queries)
- **Similarity search:** ~5ms (vector search against query_log_vec, small table)
- **Usage logging:** ~1ms (single INSERT after agent loop)
- **Simple queries:** faster than before (skip RAG, skip reranker)
- **Complex queries:** ~200ms slower (classification) but better results

## Security

- Classification rules are prompt sections -- same security model as existing prompts
- query_log contains user messages -- same DB, same access controls
- Similarity search only surfaces metadata (classification, tools), not other users' messages (single-user system)
- DecomposeQueryTool runs through normal tool approval gates

## Out of Scope

- Push notifications (separate feature, item 4 on roadmap)
- Path-based routing (infrastructure, item 5 on roadmap)
- Fine-tuning the classifier model (we use prompt evolution instead)
- Cross-agent query log sharing (mesh networking feature)
