# Context Compaction Design

**Goal:** Wire the existing ConversationSummarizer into ContextAssembler so old messages are summarized before being discarded, not silently dropped.

## Approach

Two-layer strategy: summarize on message count, trim on token budget.

1. **Summarization trigger** — message count exceeds `context_window` (20). The existing `ConversationSummarizer.summarize_if_needed()` handles this. One COUNT query per call, no-ops when nothing needs summarizing.

2. **Token budget safety net** — `_trim_to_budget()` enforces a hard ceiling. When over budget, evicts oldest summaries first, then oldest history messages. System prompt and current message are never trimmed.

## Assembly Order

`ContextAssembler.build()` produces:

```
[system prompt] + [conversation summaries] + [recent history] + [current message]
```

Steps:
1. Call `summarizer.summarize_if_needed(conversation_id)` — archives old messages
2. Fetch all summaries for this conversation from `conversation_summaries` table
3. Concatenate summaries into a single system message: `[Previous conversation summary]: ...`
4. Fetch recent history (last `history_limit` messages)
5. Apply token budget trim if needed

## Token Budget

Default `max_tokens=8000` passed by the executor. Leaves room for LLM response within typical 16K-32K context windows.

## Trim Priority

When over token budget:
1. Drop oldest summaries first (least relevant compressed context)
2. Drop oldest history messages (standard behavior)
3. Never trim system prompt or current message

## Summary Format

Multiple summaries concatenated into one message to avoid polluting the message array:

```json
{"role": "system", "content": "[Previous conversation summary]:\n\n<summary 1>\n\n<summary 2>"}
```

## Files

- `odigos/core/context.py` — add summarizer param, fetch/inject summaries, update trim
- `odigos/core/agent.py` — pass summarizer to ContextAssembler
- `odigos/main.py` — pass summarizer through to Agent

## Not Doing

- Hooks (before_compaction/after_compaction) — YAGNI
- Cascading tiers or summary-of-summaries
- Token-based summarization triggers
- Config for max_tokens (hardcode 8000, make configurable later if needed)
