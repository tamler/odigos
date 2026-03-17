# Adaptive Intelligence v1 Design

## Goal

Add a query classifier that categorizes incoming messages and adjusts the pipeline accordingly. Simple queries skip heavy RAG. Document queries use optimized search terms. All queries are logged for future evolution integration.

This is the minimal v1. The full spec (`2026-03-17-adaptive-intelligence-design.md`) remains as the north star for evolvable rules, similarity detection, and strategist wiring.

## What v1 does

1. **Classify** every incoming message as: `simple`, `standard`, `document_query`, `complex`, or `planning`
2. **Adjust** the pipeline: skip RAG for simple, use extracted search queries for document_query, pass sub-questions as hints for complex
3. **Log** classification, tools used, duration, and evaluation score for every query

## What v1 does NOT do

- Evolvable heuristic rules (hardcoded for now)
- Routing rules prompt section
- Similarity detection
- decompose_query tool
- Strategist reading query_log
- Evolution wiring

All deferred to v2.

## Component 1: Query Classifier

New module `odigos/core/classifier.py`.

### Tier 1: Hardcoded Heuristics (~0ms)

```python
def _classify_heuristic(message: str) -> str | None:
    """Fast heuristic classification. Returns None if uncertain."""
    stripped = message.strip()
    words = stripped.split()

    lower = stripped.lower()

    # Check specific categories first (most to least specific)

    # Document query: references documents explicitly
    doc_signals = ("in the document", "in the file", "in the pdf", "from the document",
                   "across all", "in all documents", "search for", "search the")
    if any(s in lower for s in doc_signals):
        return "document_query"

    # Complex: multiple questions, comparison requests
    complex_signals = ("compare", "difference between", "step by step",
                       "walk me through", "analyze", "and also", "additionally")
    if any(s in lower for s in complex_signals):
        return "complex"

    # Planning
    planning_signals = ("plan for", "schedule", "how should i", "help me figure out",
                        "what steps", "create a plan")
    if any(s in lower for s in planning_signals):
        return "planning"

    # Simple: very short, greetings (checked LAST to avoid masking specific categories)
    if len(words) <= 3 and '?' not in stripped:
        if any(g in lower for g in ("hi", "hello", "hey", "thanks", "bye", "ok", "yes", "no")):
            return "simple"

    return None  # uncertain, use Tier 2
```

Checked in specificity order: document_query/complex/planning before simple.

### Tier 2: Background Model (~200ms)

When Tier 1 returns None, call the background model with:

```
Classify this user message and extract metadata. Respond ONLY in JSON.

Message: "{message}"

{
  "classification": "simple|standard|document_query|complex|planning",
  "entities": ["entity1", "entity2"],
  "confidence": 0.0-1.0,
  "search_queries": ["optimized search query 1"],
  "sub_questions": ["sub-question 1"]
}
```

Uses the configured `background_model` (default: Gemini 2.0 Flash free). Falls back to `standard` classification if the model call fails.

### Output

```python
@dataclass
class QueryAnalysis:
    classification: str       # simple, standard, document_query, complex, planning
    confidence: float         # 1.0 for heuristic, model-provided for Tier 2
    entities: list[str]       # extracted from Tier 2 (empty for Tier 1)
    search_queries: list[str] # optimized RAG queries (empty for Tier 1)
    sub_questions: list[str]  # decomposition hints (empty unless complex)
    tier: int                 # 1 = heuristic, 2 = LLM
```

## Component 2: Pipeline Adjustment

`ContextAssembler.build()` accepts optional `QueryAnalysis`:

| Classification | RAG behavior | Context adjustment |
|---|---|---|
| `simple` | Skip RAG entirely | Minimal system prompt sections |
| `standard` | Full RAG with user message | Normal context |
| `document_query` | RAG with `search_queries` if available | Document listing emphasized |
| `complex` | RAG with `search_queries` | Sub-questions included as hints |
| `planning` | Light RAG (skip reranker) | Goal context emphasized |

For `simple`: the context assembler skips `memory_manager.recall()` and returns a lightweight prompt. This saves ~200-500ms per simple message.

For `document_query` with `search_queries`: pass the optimized queries to the memory manager instead of the raw user message. Better retrieval accuracy.

For `complex` with `sub_questions`: append to the system prompt: "Consider addressing these aspects: [sub-questions]"

## Component 3: Query Log

### Migration (027)

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

### Logging Flow

1. **Before agent loop:** Classifier runs, query_log row inserted with classification metadata
2. **After agent loop:** Executor updates row with `tools_used`, `duration_ms`, `message_id` (assistant message)
3. **After evaluation:** Evaluator updates row with `evaluation_score`

The executor needs a `tools_used` set accumulator in its tool loop to track which tools were called across all turns.

## Integration Points

### Agent._run()

```python
async def _run(self, conversation_id: str, message: UniversalMessage):
    # Classify before executor
    analysis = await self.classifier.classify(message.content)

    # Pass to executor (query_analysis is keyword-only)
    response = await self.executor.execute(
        conversation_id, message.content, query_analysis=analysis,
    )
    return response
```

### Executor.execute()

Adds keyword-only `query_analysis: QueryAnalysis | None = None` after existing params. Forwards to `context_assembler.build()`. Accumulates `tools_used` set across turns. After completion, logs to `query_log`.

### ContextAssembler.build()

Adds keyword-only `query_analysis: QueryAnalysis | None = None` (before existing `max_tokens`). Uses classification to decide:
- Whether to call `memory_manager.recall()`
- What query to pass to recall (user message or optimized search queries)
- Whether to include sub-question hints

### Evaluator

After scoring, updates query_log:
```sql
UPDATE query_log SET evaluation_score = ? WHERE message_id = ?
```

## Files Modified/Created

| File | Change |
|---|---|
| `migrations/027_query_log.sql` | New: query_log table |
| `odigos/core/classifier.py` | New: QueryClassifier with Tier 1/2 |
| `odigos/core/agent.py` | Run classifier before executor |
| `odigos/core/executor.py` | Accept QueryAnalysis, tools_used accumulator, log to query_log |
| `odigos/core/context.py` | Adjust RAG/context based on classification |
| `odigos/core/evaluator.py` | Link score to query_log |
| `odigos/main.py` | Create classifier, pass to agent |
| `data/prompts/classifier.md` | New: Tier 2 classification prompt |
| `tests/test_classifier.py` | New: heuristic + integration tests |
| `tests/test_query_log.py` | New: logging tests |

## Future (v2+)

When ready to build on this foundation:
- **Evolvable rules:** Move heuristics to `classification_rules.md` prompt section
- **Similarity detection:** Add `query_log_vec` table, search past queries
- **Strategist wiring:** Read query_log stats, propose classification/routing trials
- **decompose_query tool:** Agent-callable decomposition
- **Fast LLM:** Switch classifier to Groq/dedicated fast model

Each is additive -- no rework of v1 needed.

## Performance

- Tier 1 heuristic: <1ms
- Tier 2 LLM call: ~200ms (background model, only for uncertain queries)
- Simple queries: ~200-500ms faster (skip RAG)
- query_log INSERT: ~1ms
- Net: faster for simple queries, same for standard, slightly slower for uncertain→Tier 2

## Security

- Classifier prompt is a static template (not user-editable in v1)
- query_log contains user messages -- same DB, same access controls
- No new external dependencies
