# Structured Memory System (A-MEM + Nodepad)

**Date:** 2026-04-09
**Status:** Approved
**Group:** 2 (Agent Continuity)

## Research References

- [A-MEM](https://arxiv.org/abs/2502.12110) — Zettelkasten-inspired agentic memory with structured notes, bidirectional linking, and dynamic evolution
- [Nodepad](https://github.com/mskayyali/nodepad) — 14 semantic note types, emergent thesis synthesis
- [Memory Survey 2025](https://arxiv.org/html/2603.07670v1) — Taxonomy of episodic/semantic/procedural/working memory for agents
- [Agent Memory Paper List](https://github.com/Shichun-Liu/Agent-Memory-Paper-List) — Comprehensive survey reference

---

## Goal

Replace the flat vector store (`memory_entries`) with a structured memory system where every piece of knowledge is a typed, keyword-tagged, semantically described, linked, and evolvable memory record. This improves retrieval quality through type-filtered search, link traversal, and dynamic refinement. Based on A-MEM's Zettelkasten architecture and Nodepad's semantic typing.

---

## Section 1: Data Model

### The `memories` Table

Replaces `memory_entries`. Every piece of knowledge the agent stores becomes a structured memory record.

```sql
CREATE TABLE memories (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    memory_type TEXT NOT NULL,
    keywords_json TEXT DEFAULT '[]',
    tags_json TEXT DEFAULT '[]',
    context_description TEXT,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    conversation_id TEXT,
    confidence REAL DEFAULT 0.8,
    status TEXT DEFAULT 'active',
    superseded_by TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_memories_type ON memories(memory_type);
CREATE INDEX idx_memories_status ON memories(status);
CREATE INDEX idx_memories_source ON memories(source_type, source_id);
CREATE INDEX idx_memories_conversation ON memories(conversation_id);
```

### Memory Types (9)

| Type | What it captures | Source | Example |
|------|-----------------|--------|---------|
| fact | Verifiable statement | extraction, conversation | "User's timezone is PST" |
| preference | User wants/likes/dislikes | extraction, correction | "Prefers concise responses" |
| task | Something to do or track | extraction, conversation | "Follow up on email by Friday" |
| idea | Speculative, not yet validated | extraction, conversation | "Could automate the weekly report" |
| entity | Person, project, concept | extraction | "Rachel -- tester, uses Kimi K2" |
| experience | Learned lesson from tool use | heartbeat profiling | "Search broadly first, then narrow" |
| correction | User feedback on agent behavior | correction detection | "Don't use formal tone in emails" |
| summary | Distilled conversation content | summarizer | "Discussed deployment strategy..." |
| general | Catch-all | any | Anything that doesn't fit above |

### The `memory_links` Table

Bidirectional connections between memories.

```sql
CREATE TABLE memory_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_note_id TEXT REFERENCES memories(id) ON DELETE CASCADE,
    target_note_id TEXT REFERENCES memories(id) ON DELETE CASCADE,
    relationship TEXT NOT NULL,
    strength REAL DEFAULT 1.0,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(source_note_id, target_note_id)
);

CREATE INDEX idx_memory_links_source ON memory_links(source_note_id);
CREATE INDEX idx_memory_links_target ON memory_links(target_note_id);
```

Link relationship types: `related`, `refines`, `contradicts`, `supports`, `supersedes`, `synthesized_from`.

### The `evolution_queue` Table

Deferred evolution work items, processed by the heartbeat.

```sql
CREATE TABLE evolution_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    existing_memory_id TEXT REFERENCES memories(id),
    new_content TEXT NOT NULL,
    new_source_id TEXT,
    reason TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    processed_at TEXT
);
```

Reason values: `richer_content`, `type_mismatch`, `potential_update`.

### Vector + FTS

```sql
CREATE VIRTUAL TABLE memory_vec USING vec0(
    id TEXT PRIMARY KEY,
    embedding FLOAT[768]
);

CREATE VIRTUAL TABLE memory_fts USING fts5(
    content, context_description, keywords_json,
    content='memories', content_rowid='rowid'
);
```

FTS5 sync triggers on INSERT, DELETE, UPDATE of `memories` table.

### Tables Removed

- `memory_entries` -- replaced by `memories`
- `memory_vec` (old) -- replaced by new `memory_vec`
- `memory_fts` (old) -- replaced by new `memory_fts`
- `user_facts` -- facts become memories of type `fact` or `preference`

### Tables Kept

- `entities` + `edges` -- entity graph stays; entity-type memories bridge to it via source_id
- `corrections` -- operational table with consolidated_at lifecycle tracking stays
- `agent_experiences` -- operational table with confidence feedback loop stays
- `conversation_summaries` -- stays as index into summarized ranges

---

## Section 2: Store Pipeline

### Flow

```
Input: content, source_type, source_id, conversation_id
    |
    v
1. Classification (LLM call -- cheap model)
   - Determines memory_type (fact|preference|task|...)
   - Extracts keywords (3-5 key concepts)
   - Extracts tags (1-3 categorical labels)
   - Generates context_description (1-2 sentence semantic summary)
    |
    v
2. Deduplication check
   - Embed content, search memory_vec for near-duplicates (distance < 0.15)
   - If near-duplicate found with same memory_type:
     -> Skip store, return existing record
   - If near-duplicate found with different type or richer content:
     -> Queue for evolution (INSERT into evolution_queue)
    |
    v
3. Store
   - INSERT into memories table
   - INSERT embedding into memory_vec
   - FTS5 auto-syncs via triggers
    |
    v
4. Link discovery
   - Search memory_vec for top-5 similar memories (distance < 0.4)
   - Single LLM call judges relationship for all 5 candidates
   - INSERT bidirectional links into memory_links
   - If "contradicts" found: mark older memory status='superseded'
```

### Classification Prompt

File: `data/prompts/memory_classify.md`

Receives raw content, returns JSON:

```json
{
  "memory_type": "preference",
  "keywords": ["scheduling", "morning", "meetings"],
  "tags": ["user-profile", "time-preferences"],
  "context_description": "User prefers not to have meetings scheduled before 10am, especially on Mondays."
}
```

Uses cheapest available model.

### Link Discovery Prompt

File: `data/prompts/memory_link.md`

Receives the new memory + 5 candidate memories. Returns JSON:

```json
{
  "links": [
    {"candidate_id": "abc123", "relationship": "supports", "strength": 0.8},
    {"candidate_id": "def456", "relationship": "related", "strength": 0.6},
    {"candidate_id": "ghi789", "relationship": "none"}
  ]
}
```

Single LLM call for all candidates. Skip link discovery for `summary` type memories (too broad). Skip during bulk document ingestion (when `DocumentIngester` passes `bulk=True` to `MemoryStore.store()`) -- linking deferred to evolution phase instead.

### Cost

- 1 classification LLM call per store (cheap model)
- 1 link discovery LLM call per store (cheap model, skippable)
- Total: ~2 cheap LLM calls per memory stored
- Bulk ingestion mode: classification only, linking deferred

---

## Section 3: Recall Pipeline

### Flow

```
Input: query, classification_type (from query analysis)
    |
    v
1. Type routing
   - Map classification to relevant memory_types:
     simple      -> fact, preference, entity
     standard    -> fact, preference, entity, experience, correction
     complex     -> all types (no filter)
     planning    -> task, idea, experience, fact, entity
     document_query -> general, summary, fact
    |
    v
2. Parallel search
   a. Vector search: top-20 from memory_vec, filtered by relevant types
   b. FTS5 search: top-20 from memory_fts, filtered by relevant types
   c. Entity graph: find matching entities -> 2-hop traverse -> pull entity-type memories
    |
    v
3. RRF fusion + cross-encoder reranking
   - Merge vector + FTS results via reciprocal rank fusion
   - Cross-encoder rerank top-15 candidates
   - Score threshold: keep results above 0.4
    |
    v
4. Link expansion (NEW)
   - For each top result, follow memory_links (1-hop)
   - Pull linked memories not already in results
   - Cap at 5 link-expanded memories
   - Prefer "supports" and "refines" links over "related"
    |
    v
5. Format for context
   - Group by memory_type:
     ## Relevant facts
     - fact text [confidence: 0.9]
     ## Preferences
     - preference text
     ## Related experiences
     - experience text
   - Use context_description for richer prompt text
   - Budget: ~2000 tokens total
   - Superseded memories excluded (status='active' filter)
```

### Type Routing Map

```python
TYPE_ROUTING = {
    "simple": ["fact", "preference", "entity"],
    "standard": ["fact", "preference", "entity", "experience", "correction"],
    "complex": None,  # all types
    "planning": ["task", "idea", "experience", "fact", "entity"],
    "document_query": ["general", "summary", "fact"],
}
```

### Link Expansion

After finding top results via traditional search, follow `memory_links` one hop:

```sql
SELECT m.* FROM memories m
JOIN memory_links ml ON m.id = ml.target_note_id
WHERE ml.source_note_id IN (top_result_ids)
  AND m.status = 'active'
  AND m.id NOT IN (top_result_ids)
ORDER BY ml.strength DESC
LIMIT 5
```

Single SQL query. Surfaces semantically related memories that might not match the query embedding directly.

### Context Formatting

Output grouped by type in markdown:

```markdown
## Recalled knowledge

### Facts
- User timezone is PST
- Project deadline is April 15

### Preferences
- Prefers concise responses
- Don't schedule meetings before 10am

### Experiences
- Search broadly first when using web search tool

### Related entities
- Rachel -- tester, uses Kimi K2
```

---

## Section 4: Memory Evolution

The heartbeat periodically refines existing memories when new related information arrives.

### Heartbeat Phase

Runs as a new phase after experience extraction (Phase 9), during idle time. Same gating as other evolution work -- only when budget allows and no higher-priority work.

### Evolution Triggers

**1. Deferred evolution queue.** During the store pipeline, when a near-duplicate is found with richer or different content, a row is inserted into `evolution_queue`. The heartbeat processes up to 5 queue items per cycle.

**2. High-connectivity consolidation.** Memories with 4+ incoming links are candidates for synthesis. The heartbeat processes up to 3 candidates per cycle. This is the emergent thesis pattern from Nodepad.

### Evolution Flow

```
Heartbeat evolution phase
    |
    v
1. Process evolution_queue (max 5 per cycle)
   For each queued item:
   a. Load existing memory + new content
   b. LLM decides: UPDATE, SUPERSEDE, or SKIP
      - UPDATE: refine context_description, keywords, tags in place
      - SUPERSEDE: create new memory, mark old as superseded,
        transfer links to new memory
      - SKIP: new content adds nothing, discard
   c. Mark queue item as processed
    |
    v
2. High-connectivity consolidation (max 3 per cycle)
   a. Find memories with 4+ incoming links
   b. Load the memory + all linked memories
   c. LLM decides: should these consolidate into a richer memory?
   d. If yes: create new synthesized memory, link to originals
      with relationship "synthesized_from"
```

### Evolution Prompt

File: `data/prompts/memory_evolve.md`

Receives existing memory + new information. Returns:

```json
{
  "action": "UPDATE",
  "context_description": "Updated description...",
  "keywords": ["updated", "keywords"],
  "tags": ["updated-tags"]
}
```

Or for SUPERSEDE:

```json
{
  "action": "SUPERSEDE",
  "content": "New complete memory content",
  "memory_type": "fact",
  "keywords": [...],
  "tags": [...],
  "context_description": "..."
}
```

### Consolidation Prompt

File: `data/prompts/memory_consolidate.md`

Receives a high-connectivity memory + all linked memories. Returns:

```json
{
  "should_consolidate": true,
  "content": "Synthesized insight across all related memories...",
  "memory_type": "fact",
  "keywords": [...],
  "tags": [...],
  "context_description": "..."
}
```

### Evolution Rules by Type

| Type | Evolves? | Reason |
|------|----------|--------|
| fact | Yes | Facts get corrected or enriched over time |
| preference | Yes | User preferences change |
| task | Yes | Tasks get completed, context changes |
| idea | Yes | Ideas get refined or invalidated |
| entity | Yes | Entity knowledge grows |
| experience | Rarely | Already distilled lessons |
| correction | No | Immutable records |
| summary | No | Point-in-time snapshots |
| general | Yes | May get reclassified during evolution |

### Supersession Chain

When superseded: `status='superseded'`, `superseded_by` points to replacement. History preserved for audit; superseded memories excluded from search.

### Cost

- 1 LLM call per evolution queue item (max 5 per cycle)
- 1 LLM call per consolidation candidate (max 3 per cycle)
- Total: max 8 cheap LLM calls per heartbeat cycle
- Evolution queue typically small (0-3 items between heartbeats)

---

## Section 5: Integration

### Module Structure

```
odigos/memory/
  store.py          # MemoryStore -- write pipeline (classify, embed, link)
  recall.py         # MemoryRecall -- read pipeline (typed search, link expansion)
  evolution.py      # MemoryEvolution -- heartbeat evolution job
  classifier.py     # Classify content -> memory_type + keywords + tags + context
  graph.py          # EntityGraph (unchanged)
  manager.py        # MemoryManager (updated to use MemoryStore + MemoryRecall)
  chunking.py       # ChunkingService (unchanged)
  summarizer.py     # ConversationSummarizer (updated to store type=summary)
  corrections.py    # CorrectionsManager (updated to store type=correction)
  extractor.py      # extract_knowledge (unchanged)
  resolver.py       # EntityResolver (updated to use MemoryStore)
  ingester.py       # DocumentIngester (updated to use MemoryStore)
  vectors.py        # REMOVED
```

### Caller Migration

| Caller | Old interface | New interface |
|--------|--------------|---------------|
| MemoryManager.store() | VectorMemory + EntityGraph + user_facts | MemoryStore.store() + EntityGraph |
| MemoryManager.recall() | VectorMemory.search + FTS5 + EntityGraph | MemoryRecall.search() + EntityGraph |
| CorrectionsManager.store() | corrections table + VectorMemory | corrections table + MemoryStore (type=correction) |
| CorrectionsManager.relevant() | VectorMemory.search filtered | MemoryRecall.search(memory_type="correction") |
| ConversationSummarizer | VectorMemory.store | MemoryStore.store (type=summary) |
| DocumentIngester | VectorMemory.store | MemoryStore.store (type from classifier) |
| EntityResolver | VectorMemory for entity names | MemoryStore.search(memory_type="entity") |
| ContextAssembler | MemoryManager.recall | MemoryRecall.search (grouped output) |
| Heartbeat experiences | agent_experiences table | agent_experiences stays + type=experience memories |

### Heartbeat Integration

New phase after experience extraction:

```python
# Phase 9.5: Memory evolution
if hasattr(hb, "memory_evolution") and hb.memory_evolution:
    try:
        stats = await hb.memory_evolution.run_cycle()
        if stats.get("processed", 0) > 0:
            logger.info("Memory evolution: %d processed, %d consolidated", 
                        stats["processed"], stats.get("consolidated", 0))
    except Exception:
        logger.debug("Memory evolution failed", exc_info=True)
```

### Migration Strategy

Clean cut -- no backward compatibility:

1. Drop `memory_entries`, old `memory_vec`, old `memory_fts`, `user_facts` tables
2. Create `memories`, `memory_links`, `evolution_queue`, new `memory_vec`, new `memory_fts` tables
3. Existing deployments lose stored memories on upgrade (acceptable in dev)
4. Entity graph (`entities` + `edges`) and corrections table untouched

---

## New Files Summary

| File | Type | Purpose |
|------|------|---------|
| `odigos/memory/store.py` | Module | MemoryStore -- write pipeline |
| `odigos/memory/recall.py` | Module | MemoryRecall -- read pipeline |
| `odigos/memory/evolution.py` | Module | MemoryEvolution -- heartbeat job |
| `odigos/memory/classifier.py` | Module | Content classification |
| `data/prompts/memory_classify.md` | Prompt | Type + keywords + tags + context |
| `data/prompts/memory_link.md` | Prompt | Relationship judgment |
| `data/prompts/memory_evolve.md` | Prompt | Evolution decisions |
| `data/prompts/memory_consolidate.md` | Prompt | High-connectivity synthesis |

## Modified Files Summary

| File | Change |
|------|--------|
| `odigos/memory/manager.py` | Use MemoryStore + MemoryRecall instead of VectorMemory |
| `odigos/memory/corrections.py` | Also store corrections as type=correction memories |
| `odigos/memory/summarizer.py` | Store summaries via MemoryStore |
| `odigos/memory/ingester.py` | Store chunks via MemoryStore |
| `odigos/memory/resolver.py` | Use MemoryStore for entity name search |
| `odigos/core/context.py` | Use MemoryRecall, update memory_index counts |
| `odigos/core/heartbeat/orchestrator.py` | Add memory evolution phase |
| `odigos/core/heartbeat/maintenance.py` | Wire memory_evolution |
| `odigos/bootstrap.py` | Create and wire MemoryStore, MemoryRecall, MemoryEvolution |
| `schema.sql` | Drop old tables, create new tables |
| `migrations/` | Migration for table swap |

## Removed Files

| File | Reason |
|------|--------|
| `odigos/memory/vectors.py` | Replaced by store.py + recall.py |
