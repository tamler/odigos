# Brain Compiler — 5-Pass Wiki Compilation via Sub-Agent

**Date:** 2026-04-10
**Status:** Approved
**Group:** Agent Continuity — Brain Evolution

## Research References

- [sage-wiki](https://github.com/xoai/sage-wiki) — 5-pass LLM wiki compiler: summarize, extract concepts, generate articles, cross-link, process images

---

## Goal

Periodically compile the agent's accumulated memories, entities, and conversations into a structured, interlinked knowledge wiki. Transform `data/brain/` from a flat dump of entity pages into a living knowledge base with concept articles, cross-references, and automatic staleness management. Runs as a background sub-agent dispatched by the heartbeat when enough new content has accumulated.

---

## Section 1: Compilation Trigger

### Module: `odigos/core/heartbeat/brain_compiler.py`

Thin heartbeat phase (Phase 3f) that decides when to compile and manages the dispatch lifecycle.

### Trigger Logic

```python
async def should_compile(db) -> bool:
```

Checks (in order):
1. Is there already a pending compilation task? If yes, return False (don't dispatch another).
2. Load `brain_last_compiled` from `kv` table. If NULL (never compiled) AND at least 1 entity exists → return True (first compile).
3. Count memories created since `brain_last_compiled`. Count entities created/updated since then.
4. If `new_memories >= 10 OR new_entities >= 5` → return True.
5. Fallback: if `brain_last_compiled` is older than 24h AND at least 1 new memory → return True.
6. Otherwise → return False.

Heavy users trigger compilations more frequently (proportional to their conversation volume). Light users get at most one per day.

### Dispatch

```python
async def dispatch_compilation(hb) -> str:
```

1. Build the compilation context (the sub-agent's input_artifact):
   - List current brain articles: `ls data/brain/entities/*.md data/brain/concepts/*.md` → filenames + first 100 chars each
   - New memories since last compile: query `memories WHERE created_at > brain_last_compiled AND status='active'`, max 50, fields: `id, content[:200], memory_type, keywords_json, context_description[:200], confidence, status, superseded_by`. Prioritize high-confidence + fact/preference types. If total input exceeds 6000 chars, drop lowest-confidence memories first. Truncate general/summary memories to 100 chars.
   - New/updated entities since last compile: query `entities WHERE updated_at > brain_last_compiled`, fields: `id, name, type, summary[:200]`
   - Full list of existing slugs: ALL filenames in `data/brain/entities/`, `data/brain/concepts/`, `data/brain/archive/` (prevents fragmented duplicate concepts across compilation cycles)
   - Current `data/brain/index.md` content
2. Dispatch via `hb.subagent_manager.dispatch(persona="brain-compiler", task="...", input_artifact=context, concurrency_key="heavy")`
3. Store the task_id in `kv` table as `brain_compile_task`

### Completion Check

```python
async def check_compilation(hb) -> bool:
```

Called at the start of Phase 3f each heartbeat cycle:
1. Load `brain_compile_task` from `kv`. If empty, return False.
2. Fetch the task row. If `status='done'`, call `apply_compilation(db, result_json)`, clear the kv key, return True.
3. If `status='failed'`, clear the kv key, log warning, create notification "Brain compilation failed: {error}", return False.
4. If still pending/running, return False (let it keep running).

### Heartbeat Integration

Phase 3f, after brain_maintenance (Phase 3e):

```python
# Phase 3f: Brain compilation
try:
    from odigos.core.heartbeat import brain_compiler
    applied = await brain_compiler.check_compilation(self)
    if not applied and await brain_compiler.should_compile(self.db):
        await brain_compiler.dispatch_compilation(self)
except Exception:
    logger.debug("Brain compiler phase failed", exc_info=True)
```

---

## Section 2: Brain-Compiler Persona

### File: `data/subagents/brain-compiler.md`

```yaml
---
name: brain-compiler
description: Compiles memories and entities into a structured, interlinked knowledge wiki
model: reasoning
tools: [read_file, write_file]
max_runtime_seconds: 900
workspace_roots:
  - data/brain/
---
```

### System Prompt (5-Pass Pattern)

The persona's body teaches the 5-pass compilation:

```
# Brain Compiler

You compile the agent's accumulated knowledge into an interlinked wiki.
You receive the current brain state and new memories/entities since the
last compilation. Produce a JSON manifest of file operations.

## Pass 1: Scan & Diff

Read the current brain articles and the new memories. Identify:
- New concepts that span multiple entities or memories (not yet in the brain)
- Existing articles that should be enriched with new facts
- Stale articles whose source facts have been superseded

## Pass 2: Concept Extraction

From the new memories, identify cross-cutting themes:
- Patterns that span multiple entities or conversations
- Recurring topics the user cares about
- Ideas or goals that have evolved over time

Each concept gets: name, description, related entities, source memories.
Only create a concept article if it has 3+ supporting facts from different sources.

## Pass 3: Article Generation/Update

For each new concept: generate a wiki article.
For each existing article needing enrichment: produce updated content.

Article structure:
---
type: concept (or entity)
title: {name}
related: [{list of related article slugs}]
sources: [{memory IDs or entity IDs}]
compiled_at: {ISO timestamp}
---

## {Title}

### Overview
1-3 sentence summary.

### Key Facts
- Fact 1 [source: memory:{id}]
- Fact 2 [source: entity:{id}]

### Related Concepts
- [Concept A](../concepts/concept-a.md) — brief note on relationship
- [Entity B](../entities/entity-b.md)

### See Also
- Links to other relevant articles

## Pass 4: Cross-Linking

For every article (new or updated):
- Add inline [links](../path.md) where concepts or entities are mentioned
- Ensure bidirectional linking: if A mentions B, B should mention A
- Add a "See Also" section if not already present
- IMPORTANT: If Article A needs a link to Article B, but B isn't being
  updated in this compilation, emit a "minimal update" operation for B
  that ONLY adds the backlink. Do not rewrite B's content — just add
  the link to its "See Also" section.

SLUG REUSE: You receive a list of all existing slugs. ALWAYS check
this list before creating a new concept. If a similar slug exists
(e.g., "testing-patterns" exists, don't create "test-patterns"),
update the existing article instead of creating a duplicate.

## Pass 5: Staleness Check

For existing articles not touched by passes 1-4:
- Check source memory IDs cited in the article against the input data.
  A memory is stale if its status is 'superseded' (check the superseded_by
  field) or if it no longer exists. An article is stale if ALL of its
  source memories are stale.
- Don't archive if the article has 5+ cross-links (high-connectivity = still valuable)
- Don't archive conversation summaries (they're historical records)

## Article Footer

Every article (new or updated) MUST end with:

### Feedback
[Discuss or correct this article](/?c=new&about=concept:{slug})

## Output

Return ONLY valid JSON. No markdown fences. No commentary.

{
  "operations": [
    {"op": "create", "path": "data/brain/concepts/slug.md", "content": "full markdown"},
    {"op": "update", "path": "data/brain/entities/slug.md", "content": "full markdown"},
    {"op": "archive", "path": "data/brain/concepts/old.md", "reason": "source facts superseded"}
  ],
  "new_concepts": ["slug1", "slug2"],
  "updated_articles": ["slug3"],
  "archived": ["slug4"],
  "cross_links_added": 12,
  "summary": "One-line human-readable summary of what was compiled."
}

If nothing needs to be compiled (no meaningful new content), return:
{"operations": [], "new_concepts": [], "updated_articles": [], "archived": [], "cross_links_added": 0, "summary": "No compilation needed."}
```

---

## Section 3: Post-Compilation — Applying the Manifest

### Module: `odigos/core/brain_apply.py`

```python
async def apply_compilation(db, result_json: str) -> dict:
    """Apply a brain compilation manifest to disk.
    
    Returns: {created: int, updated: int, archived: int, errors: list[str]}
    """
```

### Operation Handling

**`create`:**
1. Validate `path` starts with `data/brain/`
2. Create parent directories if needed (`Path(path).parent.mkdir(parents=True, exist_ok=True)`)
3. Validate `content` is a non-empty string
4. Write the file

**`update`:**
1. Same path validation
2. Overwrite the file (existing content replaced entirely)
3. Log the update

**`archive`:**
1. Validate source path exists
2. Compute archive path: replace `data/brain/` with `data/brain/archive/` (preserving subdirectory structure)
3. Read existing file, prepend frontmatter: `archived_at: {ISO timestamp}`, `archive_reason: {reason}`
4. Write to archive path
5. Delete the original

### Post-Apply Steps

After all operations:
1. **Regenerate index.md:** Walk `data/brain/entities/` and `data/brain/concepts/`, build a markdown index grouped by type.
2. **Append to log.md:** `## {ISO timestamp} — Brain compilation\n{summary}\nCreated: {n}, Updated: {n}, Archived: {n}\n---`
3. **Update kv:** `brain_last_compiled = datetime('now')`
4. **Create notification:** `{type: 'status', title: 'Brain compiled', body: summary}`

### Operation Ordering

Apply operations in dependency order to avoid broken references:
1. All `create` operations first (new articles that might be referenced by updates)
2. All `update` operations second (enrichments + backlinks)
3. All `archive` operations last (only after references have been updated)

This is NOT fully atomic. If a crash occurs mid-apply, the brain may have partial state. This is acceptable because: (a) single-user system, (b) the next compilation reads current state and self-repairs, (c) archive operations are last so they don't delete articles before backlinks are updated.

### Safety

- Path validation: reject any path not starting with `data/brain/`
- Content validation: reject empty content for create/update
- Partial success: if one operation fails, log the error and continue with the rest
- Manifest stored in `tasks.result_json` for re-application if needed
- The `concurrency_key="heavy"` on dispatch ensures only one compilation runs at a time (heavy pool limit = 1)

---

## Section 4: New Directory Structure

```
data/brain/
├── index.md                    # Master index (regenerated after each compilation)
├── log.md                      # Append-only operation log
├── entities/                   # Entity pages (written by brain_maintenance, enriched by compiler)
│   ├── rachel.md
│   └── odigos.md
├── concepts/                   # NEW: concept articles (created by compiler)
│   ├── deployment-workflow.md
│   └── testing-patterns.md
├── topics/                     # Topic indexes (existing, written by brain_maintenance)
│   └── person.md
├── conversations/              # Conversation summaries (existing)
├── synthesis/                  # Proactive findings (existing)
└── archive/                    # NEW: archived stale articles (moved by compiler)
    └── concepts/
        └── old-topic.md
```

The only new directories are `concepts/` and `archive/`. Created on first use.

---

## Section 5: Integration Summary

### New Files

| File | Purpose |
|------|---------|
| `odigos/core/heartbeat/brain_compiler.py` | Trigger: should_compile, dispatch_compilation, check_compilation |
| `odigos/core/brain_apply.py` | Apply manifest: create/update/archive files, regenerate index |
| `data/subagents/brain-compiler.md` | 5-pass compiler persona |
| `tests/test_brain_compiler.py` | Trigger logic tests |
| `tests/test_brain_apply.py` | Manifest application tests |

### Modified Files

| File | Change |
|------|--------|
| `odigos/core/heartbeat/orchestrator.py` | Add Phase 3f: brain compilation trigger + check |
| `odigos/core/heartbeat/brain_maintenance.py` | Skip entity page overwrite when compiled_at > entity.updated_at |

### What Stays Unchanged (with one refinement)

- `brain_maintenance.py` — still projects entities to files every heartbeat. **Refinement:** before overwriting an entity page, brain_maintenance checks the page's frontmatter for a `compiled_at` timestamp. If `compiled_at > entity.updated_at`, skip the overwrite — the compiler's enriched version takes precedence. brain_maintenance only writes when it has data newer than the compiler. This prevents race conditions where maintenance overwrites the compiler's enriched output.
- `BrainWriter` / `BrainReader` — untouched. Compiler uses the same markdown format.
- `data/sources/` — untouched. Compiler reads memories, not raw sources.
- `memories` / `entities` / `edges` tables — read-only from the compiler's perspective.
- `kv` table — used for `brain_last_compiled` and `brain_compile_task` (existing table, no schema change).

### Relationship to Existing Systems

- **brain_maintenance** writes entity pages → **brain_compiler** reads and enriches them
- **memories table** provides new content → **brain_compiler** synthesizes into concept articles
- **sub-agent infrastructure** executes the compilation → **brain_apply** writes the result to disk
- **notification system** tells the user compilation happened

No new tables. No schema changes. Uses existing kv table, sub-agent dispatch, notification system.

---

## Section 6: Deliberately NOT in V1

- Image/diagram generation for articles
- User editing of brain articles (output is compiler-managed; user input goes through chat → memories)
- Real-time compilation on every memory write (too expensive; batch via trigger thresholds)
- Brain search UI (brain files are on disk; search is via the existing memory system)
- Multi-user brain merging
- Compilation rollback (archive preserves history; re-compilation can fix errors)
- Concept hierarchy (concepts are flat; tagging/nesting deferred)

---

## Success Metrics

This feature is successful if:
- After 20+ conversations, the brain contains concept articles that synthesize knowledge across entities (not just entity dumps)
- Cross-links between articles are relevant and bidirectional
- Stale articles get archived when their source facts are superseded
- Compilation runs proportionally to usage (heavy users compile more often)
- The compilation sub-agent completes within the 900s timeout
- Brain files are readable as standalone markdown (browseable in any markdown viewer)
