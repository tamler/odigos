# Phase 1 Design: Memory

**Date:** 2026-03-04
**Status:** Approved
**Milestone:** "It remembers me" -- agent recalls past conversations, extracts entities, builds a knowledge graph

---

## Scope

Build the memory layer: vector search via sqlite-vec, entity-relationship graph, entity resolution pipeline, conversation summarization, and upgraded context assembly that injects relevant memories into every LLM call.

### Decisions

| Decision | Choice | Reasoning |
|----------|--------|-----------|
| Embeddings | OpenRouter API (openai/text-embedding-3-small, 1536d) | Defer local EmbeddingGemma to VPS deployment. One API key for everything. |
| Entity extraction | Inline with conversation LLM | Ask LLM to extract entities as part of its response. One call, no extra cost. |
| Summarization trigger | When messages fall out of context window | Last 20 turns are already in context. Only summarize + embed when messages age out. |
| Entity resolution | Full pipeline (exact, fuzzy, alias, vector, LLM tiebreaker) | Prevents graph fragmentation from day one. |
| Local NLP pipeline | Deferred | No local model yet. Entity extraction via conversation LLM. Swap to local when Qwen is running on VPS. |
| Personality system | Deferred to Phase 1b | Memory is the priority. Personality is a follow-up. |

---

## New Database Tables (migration 002)

```sql
-- Entity-relationship graph
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    aliases_json TEXT,
    confidence REAL DEFAULT 1.0,
    status TEXT DEFAULT 'active',
    properties_json TEXT,
    summary TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    source TEXT
);

CREATE TABLE IF NOT EXISTS edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT REFERENCES entities(id),
    relationship TEXT NOT NULL,
    target_id TEXT REFERENCES entities(id),
    strength REAL DEFAULT 1.0,
    metadata_json TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    last_confirmed TEXT
);

CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
CREATE INDEX IF NOT EXISTS idx_edges_rel ON edges(relationship);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);

-- Conversation summaries
CREATE TABLE IF NOT EXISTS conversation_summaries (
    id TEXT PRIMARY KEY,
    conversation_id TEXT REFERENCES conversations(id),
    start_message_idx INTEGER,
    end_message_idx INTEGER,
    summary TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
```

sqlite-vec virtual table created programmatically (not in SQL migration):
```python
# 1536 dimensions for text-embedding-3-small
CREATE VIRTUAL TABLE IF NOT EXISTS memory_vectors USING vec0(
    id TEXT PRIMARY KEY,
    embedding FLOAT[1536],
    +source_type TEXT,
    +source_id TEXT,
    +content_preview TEXT,
    +created_at TEXT
);
```

---

## New Modules

```
odigos/
  providers/
    embeddings.py          # OpenRouter embedding API wrapper
  memory/
    __init__.py
    manager.py             # Unified recall/store interface
    vectors.py             # sqlite-vec wrapper + search
    graph.py               # Entity queries (recursive CTEs)
    resolver.py            # Entity resolution pipeline
    summarizer.py          # Conversation summarization + embedding
```

---

## Embedding Provider (providers/embeddings.py)

- httpx.AsyncClient, same pattern as openrouter.py
- Calls OpenRouter /api/v1/embeddings with model "openai/text-embedding-3-small"
- Input: text string or list of strings (batch)
- Output: list of float vectors (1536 dimensions each)
- Uses the same OPENROUTER_API_KEY

---

## Vector Memory (memory/vectors.py)

- Wraps sqlite-vec for insert and search operations
- `store(text, source_type, source_id)`:
  - Call embedding provider to get vector
  - INSERT into memory_vectors with metadata
- `search(query, limit=5)`:
  - Embed the query
  - KNN search via sqlite-vec
  - Return list of MemoryResult(content_preview, source_type, source_id, similarity)
- Creates the vec0 virtual table on initialization if not exists

---

## Entity Graph (memory/graph.py)

Query helpers for the entity-relationship tables:
- `find_entity(name)` -- search by name or alias (JSON contains check)
- `create_entity(type, name, properties)` -- INSERT with UUID
- `update_entity(id, updates)` -- UPDATE properties, aliases, confidence
- `create_edge(source_id, relationship, target_id, metadata)` -- INSERT edge
- `traverse(entity_id, depth=2)` -- recursive CTE for multi-hop traversal
- `get_related(entity_id)` -- one-hop: all entities connected to this one
- `merge_entities(keep_id, remove_id)` -- merge: reassign edges, combine aliases, delete duplicate

---

## Entity Resolution (memory/resolver.py)

For each candidate entity extracted from conversation:

1. **Exact match**: SELECT WHERE name = ?
2. **Fuzzy match**: SELECT WHERE name LIKE '%partial%' AND type = ?
3. **Alias match**: search aliases_json for the name
4. **Vector match**: embed the name, cosine similarity against entity name embeddings
5. **LLM tiebreaker**: if multiple candidates, ask cheap model "Is X the same as Y given this context?"

Results:
- Match found (confidence > 0.8): merge into existing entity, add alias
- No match: create new entity
- Uncertain (0.3-0.8): create with low confidence, flag for promotion if referenced again

---

## Conversation Summarizer (memory/summarizer.py)

Watches the context window boundary:
- Context window = last 20 messages
- When message 21+ exists and hasn't been summarized:
  - Gather the unsummarized messages
  - Call LLM: "Summarize this conversation segment in 2-3 sentences. Focus on key facts, decisions, and entities."
  - Store summary in conversation_summaries table
  - Embed the summary into memory_vectors (source_type="conversation_summary")

This runs as part of the reflector's post-response processing.

---

## Memory Manager (memory/manager.py)

Unified interface for the agent core:

**recall(query, limit=5)**:
1. Vector search: embed query, find top-K similar memories
2. Entity lookup: find entities mentioned in the query
3. Graph traversal: get related entities (1-hop) for found entities
4. Combine and rank results by relevance + recency
5. Return formatted context string for injection into prompt

**store(conversation_id, user_message, assistant_response, extracted_entities)**:
1. Run entity resolution for each extracted entity
2. Create/update entities and edges
3. Embed the user message (for direct semantic search)
4. Check if summarization is needed (messages > window), trigger if so

---

## Context Assembly Upgrade (core/context.py)

Current: system prompt + history + current message
Upgraded to:

1. **System prompt** (with entity extraction instruction appended)
2. **Relevant memories** (top 3-5 from memory_manager.recall)
3. **Related entities** (entities mentioned in recent context)
4. **Conversation history** (last 20 messages)
5. **Current message**

Memory injection format:
```
## Relevant memories
- [2 days ago] You discussed the Odigos architecture with Alex. Key decisions: SQLite for everything, four-tier model routing.
- [1 week ago] You mentioned preferring morning meetings after 10am.

## Known entities
- Alex: person, business partner, works on Odigos project
- Odigos: project, personal AI agent
```

---

## Inline Entity Extraction

System prompt addition:
```
After your response, on a new line, include extracted entities in this exact format:
<!--entities
[{"name": "...", "type": "person|project|preference|concept", "relationship": "...", "detail": "..."}]
-->
Only include entities if the conversation mentions specific people, projects, preferences, or important concepts.
If none are relevant, omit the block entirely.
```

The reflector:
1. Parses the `<!--entities ... -->` block from the LLM response
2. Strips it from the user-visible response
3. Passes extracted entities to memory_manager.store()

---

## New Dependencies

```
sqlite-vec >= 0.1.0   # Vector search extension for SQLite
```

---

## Integration Points

- **reflector.py** upgraded: after storing the message, calls memory_manager.store() with extracted entities
- **context.py** upgraded: calls memory_manager.recall() before building the prompt
- **agent.py**: passes memory_manager to reflector and context assembler
- **main.py**: initializes memory_manager, embedding provider, passes to agent
- **db.py**: loads sqlite-vec extension on initialization
