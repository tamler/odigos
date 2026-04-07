# Memory Redesign — Wiki Files + DB Index

**Date:** 2026-04-07
**Status:** Approved
**Goal:** Durable, rebuildable knowledge persistence. Files are the durable layer (survive DB drops, portable across machines). DB is the operational layer (fast queries, vectors, FTS). Wiki files are a structured projection that can rebuild the DB.

## Context

The current memory system stores everything in SQLite — entities, facts, user profile, conversation summaries, vectors. If the DB is dropped (as happened during the conversation foundation deploy), all compiled knowledge is lost. Entity extraction depends on the LLM embedding `<!--entities-->` HTML comments in its responses, which is fragile. Assistant responses are never stored in memory. There is no periodic maintenance, no dedup, no lint pass for stale or contradictory knowledge.

## Design

### 1. Directory Structure

```
data/
  sources/                    # Raw external content (immutable)
    2026-04-07-karpathy-llm-wiki.md
    ...
  wiki/                       # Compiled knowledge (agent-maintained projection)
    index.md                  # Master catalog of all entities and topic pages
    log.md                    # Append-only record of wiki operations
    entities/                 # Full entity pages (graduated entities only)
      jacob.md
      odigos.md
      ...
    topics/                   # Type-level index files (small entities live here)
      people.md
      tools.md
      projects.md
      ...
    synthesis/                # Cross-cutting analysis, filed query results
      ...
    conversations/            # Conversation summary archives
      2026-04-07-capabilities-and-horror-story.md
      ...
  agent/                      # Identity and behavior (existing, unchanged)
    identity.md
    capabilities.md
    ...
```

**`data/sources/`** — cleaned markdown of scraped pages, uploaded documents, external content. Immutable — the agent reads from them but never modifies them. Named with date prefix. YAML frontmatter with `url`, `scraped_at`, `content_type`, `sha256`.

**`data/wiki/`** — agent-generated and agent-maintained. Every file has YAML frontmatter with enough structure to rebuild DB tables (entity IDs, source references, relationships). The heartbeat writes these. Humans can browse but don't edit.

**`data/wiki/index.md`** — catalog of all entities and topic pages with one-line descriptions. The agent reads this first when searching.

**`data/wiki/log.md`** — append-only record: ingests, extractions, lint passes, page graduations. Parseable with grep.

### 2. Entity Extraction

The `<!--entities-->` HTML comment approach is removed. The reflector runs a dedicated extraction step after every response.

```
User message + Assistant response
        |
  Reflector.reflect()
        |
  1. Store assistant message via bus.publish()
  2. Extract entities + facts via cheap LLM call (NEW)
  3. Store in DB immediately (entities, edges, user_facts)
  4. Memory manager store() for vector embeddings
```

The extraction is a single cheap LLM call with structured JSON output:

```json
{
  "entities": [
    {"name": "Kie.ai", "type": "tool", "summary": "Music generation API"}
  ],
  "facts": [
    {"text": "Jacob prefers Groq for STT", "category": "preference", "about": "Jacob"}
  ],
  "relationships": [
    {"from": "Odigos", "relationship": "uses", "to": "Kie.ai"}
  ]
}
```

Uses the background/cheap model to keep cost low.

**Relevance gate:** Skip extraction if the user message is under 20 characters or matches small-talk patterns ("ok", "thanks", "cool", "yes", "no", "got it"). No point burning tokens on empty turns.

**Exact dedup at write time:** SHA-256 hash of fact text checked before INSERT. Semantic dedup handled by the lint pass.

**What gets extracted:** Named entities (people, tools, projects, places, organizations), user facts (preferences, knowledge, goals, habits), relationships between entities. NOT opinions, small talk, or ephemeral conversation content.

### 3. Wiki File Format

Every wiki file has YAML frontmatter that serves as both human-readable metadata and the rebuild seed for DB reconstruction.

**Entity page** (`data/wiki/entities/jacob.md`):

```markdown
---
id: a1b2c3d4e5f6
type: person
aliases: [Jake, J]
confidence: 0.95
sources: [conv:abc123, conv:def456, doc:2026-04-07-profile]
updated_at: 2026-04-07T08:30:00Z
---

# Jacob

Project owner of Odigos. Prefers direct communication, no time estimates.

## Facts
- Prefers Groq for STT [conv:abc123]
- Tests with Bob on odigos.one, not locally [conv:def456]
- Deep Go expertise, new to React frontend [conv:ghi789]

## Relationships
- **owns** -> [Odigos](odigos.md)
- **uses** -> Groq, OpenRouter
- **manages** -> Bob, Honey, Rachel, Sales
```

**Topic index** (`data/wiki/topics/tools.md`):

```markdown
---
type: topic_index
entity_type: tool
updated_at: 2026-04-07T08:30:00Z
---

# Tools

## Full Pages
- [Kie.ai](../entities/kie-ai.md) -- Music generation API, V5.5

## Index
- **Groq** -- LLM provider, used for STT whisper [conv:abc123]
- **OpenRouter** -- LLM provider, multi-model routing [conv:def456]
- **sqlite-vec** -- Vector extension for SQLite [doc:2026-03-15-setup]
```

**Conversation summary** (`data/wiki/conversations/2026-04-07-capabilities.md`):

```markdown
---
id: abc123def456
channel: web
message_count: 4
created_at: 2026-04-07T08:14:00Z
---

# Capabilities and Horror Story

User asked about agent capabilities (46 tools, 50 skills). Then requested
a short horror story -- "The Mirror" about a woman whose reflection stops
following her movements.

## Key Facts Extracted
- User exploring agent capabilities [-> jacob.md]
```

**Source file** (`data/sources/2026-04-07-karpathy-llm-wiki.md`):

```markdown
---
url: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
title: LLM Wiki -- Karpathy
scraped_at: 2026-04-07T08:30:00Z
content_type: article
sha256: abc123...
---

# LLM Wiki

A pattern for building personal knowledge bases using LLMs...
```

**Key conventions:**
- `sources` array in entity frontmatter links to conversations/documents (provenance)
- Facts have inline source citations `[conv:id]` or `[doc:filename]`
- Entities graduate from topic index to full page at 3+ facts or 2+ relationships
- Frontmatter `id` matches the DB entity ID for rebuild
- Source files are immutable — never modified after creation
- SHA-256 in source frontmatter enables dedup (don't re-scrape same content)

### 4. Provenance

Every fact and entity tracks where it came from via a `source_type` and `source_id`:

| source_type | source_id | Example |
|---|---|---|
| `conversation` | message_id | Fact extracted from chat turn |
| `document` | document_id | Fact extracted from uploaded/ingested doc |
| `scrape` | source filename | Fact extracted from scraped web page |
| `user_correction` | correction_id | Fact from explicit user correction |

The `source_id` is stored on the DB row (entities, user_facts) and rendered as inline citations in wiki files. The lint pass validates that referenced sources still exist.

### 5. Sync vs Async Split

**Sync (reflector, immediate):**
- Extract entities and facts from conversation (cheap LLM call)
- SHA-256 dedup check before INSERT
- Store in DB tables (entities, edges, user_facts)
- Embed in memory_vec for vector search
- Available to the very next turn

**Write-ahead queue:** The reflector also inserts a row into `pending_wiki_writes` (entity_id, fact_id, operation type). This ensures that if the process crashes after the DB write but before the heartbeat runs, the wiki catches up on next startup. The heartbeat drains this queue.

**Async (heartbeat phase 3d, every 30s):**
- Drain `pending_wiki_writes` queue
- Write/update wiki markdown files for changed entities
- Build cross-references between entity pages (bidirectional — if A→B exists, B's page shows the backlink)
- Graduate entities from topic index to full page
- Rebuild `data/wiki/index.md`
- Write conversation summaries
- Append to `data/wiki/log.md`

**Lint pass (heartbeat, every 10 ticks / ~5 min):**
- Stale claims — facts with old sources and no recent confirmation
- Orphan entities — no relationships and no recent mentions
- Contradictions — conflicting facts about the same entity (cheap LLM call per batch)
- Missing pages — entities referenced in relationships but lacking a wiki page
- Source validation — referenced source files still exist
- Semantic dedup — generate merge proposals, not destructive merges

Lint findings are written to `data/wiki/log.md`. Semantic dedup produces merge proposals (e.g., "Entity 'Python Script' and 'script.py' may be the same") logged for the agent to present to the user or resolve during idle time. No automatic destructive merges.

### 8. User-Initiated Deletion ("Forget")

When the user says "forget that I like coffee" or similar:

1. Agent identifies the fact/entity to delete
2. Delete from DB (user_facts, entities, edges)
3. Remove from wiki file (edit the markdown, remove the line)
4. Append a `[FORGET]` entry to `data/wiki/log.md` with the deleted content
5. The log entry prevents the lint pass from re-extracting the fact from old conversation summaries

The forget log acts as a suppression list. During extraction, facts matching a forget entry are skipped.

### 6. Source Archival

When the agent scrapes a web page or processes an external document:

1. Clean to markdown (existing scraper pipeline)
2. Write to `data/sources/YYYY-MM-DD-slugified-title.md` with frontmatter
3. SHA-256 check — skip if identical content already archived
4. Store reference in `documents` table with `file_path` pointing to source file
5. Chunk and embed for vector search (existing pipeline)

Source files are immutable. Full content is always available on disk (no 500-char truncation). The `document_text` table becomes redundant for new sources.

### 7. DB Rebuild from Files

When the DB is empty on startup and `data/wiki/` has content:

1. `schema.sql` creates empty tables (existing)
2. Detect `data/wiki/` exists with content
3. Parse entity pages frontmatter → INSERT into entities, edges
4. Parse topic indexes → INSERT remaining entities
5. Parse facts with source refs → INSERT into user_facts
6. Parse `data/sources/` frontmatter → INSERT into documents
7. Re-embed all content into memory_vec
8. FTS triggers rebuild automatically
9. Parse conversation summaries → INSERT into conversation_summaries
10. Log: "Rebuilt from wiki files: X entities, Y facts, Z sources"

**What can NOT be rebuilt:** Full conversation message history. The conversation summaries in `data/wiki/conversations/` provide context for what was discussed, but individual messages are operational data that lives only in the DB.

**The rebuild is a safety net, not the normal path.** Normal operation: DB is primary for writes, wiki files are the projection. Rebuild only fires on empty DB with existing wiki files.

## File Changes

| File | Change |
|---|---|
| `odigos/memory/wiki_writer.py` | **New** — writes entity pages, topic indexes, index.md, log.md |
| `odigos/memory/wiki_reader.py` | **New** — parses wiki files for DB rebuild |
| `odigos/memory/source_archiver.py` | **New** — saves cleaned markdown to data/sources/ |
| `odigos/memory/extractor.py` | **New** — structured entity/fact extraction via cheap LLM call |
| `odigos/core/reflector.py` | Remove HTML comment entity parsing, add extractor call |
| `odigos/memory/manager.py` | Update store() to use new extractor output |
| `odigos/memory/graph.py` | Add provenance fields (source_type, source_id) to entity creation |
| `odigos/core/heartbeat/orchestrator.py` | Add phase 3d: wiki maintenance |
| `odigos/core/heartbeat/wiki_maintenance.py` | **New** — pending writes, graduation, cross-refs, index, lint |
| `odigos/db.py` | Add rebuild-from-wiki detection on empty DB startup |
| `odigos/tools/scrape.py` | Call source_archiver after scraping |
| `odigos/memory/ingester.py` | Call source_archiver for document ingestion |
| `schema.sql` | Add source_type, source_id, content_hash to entities and user_facts; add pending_wiki_writes table |

## What Doesn't Change

- Vector memory search (memory_vec, memory_fts) — same tables, same search
- Conversation storage — messages go through MessageBus as before
- Context assembly — build_planned() still pulls from same DB tables
- Tool registry, executor, classifier — untouched
- Frontend — no UI changes in this spec
- User profile tables — existing profiling heartbeat phases unchanged

## What This Replaces

| Old Pattern | New Pattern |
|---|---|
| `<!--entities-->` HTML comments in LLM response | Dedicated extractor LLM call in reflector |
| Knowledge only in DB | DB primary + wiki files as durable projection |
| No provenance on facts/entities | source_type + source_id on every record |
| Scraped content in DB only (truncated) | Full cleaned markdown in data/sources/ |
| No memory maintenance | Heartbeat lint pass every 5 min |
| No dedup | SHA-256 at write time, semantic dedup in lint |
| DB drop = total knowledge loss | Rebuild from wiki files + sources |
| Assistant responses never stored | Both user and assistant content available for extraction |
| 500-char content_preview truncation | Full content in source files, no truncation |
