# Correction Logging Design

## Goal

Detect when users correct the agent, store corrections with semantic embeddings, and inject relevant past corrections into future context to avoid repeating mistakes.

## Current State

- No correction detection or storage exists
- DB schema defined in ARCHITECTURE.md but not migrated
- Reflector parses `[ENTITY]` blocks from LLM responses — same pattern extends to corrections
- VectorMemory (sqlite-vec) operational for semantic similarity search
- ContextAssembler + prompt_builder ready for new context sections

## Changes

### 1. CorrectionsManager (`odigos/memory/corrections.py`)

New class following MemoryManager patterns:

- `store(conversation_id, original_response, correction_text, context, category)` — inserts into `corrections` table and embeds context via VectorMemory for future retrieval
- `relevant(query, limit=5)` — vector similarity search against correction context, returns formatted string for prompt injection

Uses existing `VectorMemory` with `source_type="correction"`.

### 2. DB migration (`007_corrections.sql`)

```sql
CREATE TABLE corrections (
    id TEXT PRIMARY KEY,
    timestamp TEXT DEFAULT (datetime('now')),
    conversation_id TEXT,
    original_response TEXT,
    correction TEXT,
    context TEXT,
    category TEXT,
    applied_count INTEGER DEFAULT 0
);
```

Categories: "tone", "accuracy", "preference", "behavior", "tool_choice".

No `rule_extracted` column (deferred to self-skill-building phase). No `improvement_proposals` table (deferred).

### 3. System prompt extension

Add to `build_system_prompt()`:

1. **Detection instructions** — tell the LLM to output a `[CORRECTION]` block when the user's message corrects a previous response
2. **Learned corrections section** — inject relevant past corrections retrieved via vector search

Block format (LLM outputs when detecting correction):

```
[CORRECTION]
{"original": "summary of what was wrong", "correction": "what user wants instead", "category": "preference", "context": "brief situation description"}
[/CORRECTION]
```

### 4. Reflector extension

Add second regex parse (after `[ENTITY]` extraction) for `[CORRECTION]` blocks. On match, call `CorrectionsManager.store()`.

## Data Flow

```
User sends follow-up message
  -> ContextAssembler.build()
      -> CorrectionsManager.relevant(message)     [NEW]
      -> build_system_prompt(corrections=...)      [EXTENDED]
  -> Executor runs LLM
      -> LLM detects correction, outputs [CORRECTION] block
  -> Reflector.reflect()
      -> Parse [CORRECTION] block                  [NEW]
      -> CorrectionsManager.store()                [NEW]
      -> VectorMemory.store() for future retrieval [NEW]
```

## What's NOT in scope

- Rule extraction from repeated corrections (deferred to self-skill-building)
- `improvement_proposals` table
- Telegram approval workflow / inline keyboards
- `applied_count` incrementing (schema tracks it, logic added later)
- Hot-reloadable correction rules

## Testing

- CorrectionsManager.store() persists to DB and embeds via VectorMemory
- CorrectionsManager.relevant() returns semantically similar corrections
- Reflector parses [CORRECTION] blocks and calls store()
- System prompt includes learned corrections section when corrections exist
- System prompt includes detection instructions
- End-to-end: correction detected -> stored -> injected in next context
