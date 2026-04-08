# Agent Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Four improvements to context assembly, retrieval, and LLM communication — structured output fallback, static-first prompt caching, pyramid expansion in recall, and parallel tool call instruction.

**Architecture:** `complete_json()` on the LLM provider handles JSON output via 3-tier fallback. `build_planned()` reorders sections static-first for cache optimization. `recall()` gains pyramid expansion with token budget and relevance-gated full content loading. A one-line prompt addition enables parallel tool calls.

**Tech Stack:** Python 3.12, aiosqlite, jsonschema, tiktoken (existing), sentence-transformers cross-encoder (existing)

---

## File Structure

| File | Responsibility |
|------|---------------|
| `odigos/providers/base.py` | Add `cached_tokens` field to `LLMResponse` |
| `odigos/providers/llm.py` | Add `complete_json()`, `supports_explicit_cache`, populate `cached_tokens` |
| `odigos/core/json_utils.py` | Upgrade `parse_json_response()` with balanced-brace regex |
| `odigos/core/llm_prompt.py` | Upgrade `call_llm()` to pass `response_format`, upgrade `run_prompt()` to return `(dict, bool)` |
| `odigos/memory/extractor.py` | Switch to `complete_json()` |
| `odigos/memory/manager.py` | Pyramid expansion: `token_budget` param, `_format_results()`, `strategy` param on `_hybrid_search()` |
| `odigos/core/context.py` | Reorder `build_planned()` static-first, Anthropic cache blocks, pass budget to recall, parallel tool instruction |
| `tests/test_complete_json.py` | **New** — Tests for `complete_json()` |
| `tests/test_pyramid_recall.py` | **New** — Tests for pyramid expansion |

---

### Task 1: LLMResponse cached_tokens + JSON Utils Upgrade

Add `cached_tokens` to the response dataclass and improve JSON parsing.

**Files:**
- Modify: `odigos/providers/base.py`
- Modify: `odigos/core/json_utils.py`

- [ ] **Step 1: Add cached_tokens to LLMResponse**

In `odigos/providers/base.py`, add to the `LLMResponse` dataclass after `tool_calls`:

```python
    cached_tokens: int = 0
```

- [ ] **Step 2: Upgrade parse_json_response with balanced-brace extraction**

In `odigos/core/json_utils.py`, replace the final regex fallback (`re.search(r'\{.*\}', text, re.DOTALL)`) with a balanced-brace finder that returns the LARGEST `{}` block:

```python
def _find_largest_json_block(text: str) -> str | None:
    """Find the largest balanced {} block in text."""
    best = None
    for i, ch in enumerate(text):
        if ch == '{':
            depth = 0
            for j in range(i, len(text)):
                if text[j] == '{':
                    depth += 1
                elif text[j] == '}':
                    depth -= 1
                    if depth == 0:
                        candidate = text[i:j+1]
                        if best is None or len(candidate) > len(best):
                            best = candidate
                        break
    return best
```

Replace the existing `re.search(r'\{.*\}', text, re.DOTALL)` line with a call to `_find_largest_json_block(text)`.

- [ ] **Step 3: Run existing tests**

Run: `python3 -m pytest tests/ -q --ignore=tests/test_relevance.py 2>&1 | tail -10`
Expected: No regressions

- [ ] **Step 4: Commit**

```bash
git add odigos/providers/base.py odigos/core/json_utils.py
git commit -m "feat: cached_tokens on LLMResponse, balanced-brace JSON extraction"
```

---

### Task 2: complete_json() on LLM Provider

Add the 3-tier fallback JSON method and cache detection.

**Files:**
- Modify: `odigos/providers/llm.py`
- Create: `tests/test_complete_json.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_complete_json.py` with tests using a mock LLM provider:

1. `test_complete_json_tier1_json_schema` — provider returns valid JSON when `response_format` is set. Verify parsed dict returned with `success=True`.
2. `test_complete_json_tier2_json_object_fallback` — tier 1 raises an error (simulating 400), tier 2 succeeds with json_object mode.
3. `test_complete_json_tier3_regex_fallback` — both tier 1 and 2 fail, response content has JSON embedded in text like `"Here's the result: {"entities": []}..."`. Verify regex extracts it.
4. `test_complete_json_all_tiers_fail` — response is "I can't do that". Verify returns `({}, False)`.
5. `test_complete_json_schema_validation` — tier 2 returns JSON that doesn't match provided schema. Verify returns `({}, False)` with warning log.
6. `test_supports_explicit_cache_anthropic` — model name contains "claude". Returns True.
7. `test_supports_explicit_cache_groq` — model name is "meta-llama/...". Returns False.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_complete_json.py -v`
Expected: FAIL

- [ ] **Step 3: Implement complete_json()**

In `odigos/providers/llm.py`, add to `LLMClient`:

```python
    async def complete_json(
        self,
        messages: list[dict],
        schema: dict | None = None,
        **kwargs,
    ) -> tuple[dict, bool]:
        """LLM call with 3-tier JSON fallback. Returns (parsed_dict, success)."""
        from odigos.core.json_utils import parse_json_response

        # Tier 1: json_schema (if schema provided)
        if schema:
            try:
                resp = await self.complete(
                    messages,
                    response_format={"type": "json_schema", "json_schema": {"name": "response", "schema": schema}},
                    **kwargs,
                )
                parsed = json.loads(resp.content)
                return parsed, True
            except Exception:
                pass  # Fall through to tier 2

        # Tier 2: json_object
        try:
            resp = await self.complete(
                messages,
                response_format={"type": "json_object"},
                **kwargs,
            )
            parsed = json.loads(resp.content)
            # Validate against schema if provided
            if schema:
                import jsonschema
                try:
                    jsonschema.validate(parsed, schema)
                except jsonschema.ValidationError as e:
                    logger.warning("JSON schema validation failed: %s", e.message[:100])
                    return {}, False
            return parsed, True
        except Exception:
            pass  # Fall through to tier 3

        # Tier 3: regex extraction from freeform
        try:
            resp = await self.complete(messages, **kwargs)
            parsed = parse_json_response(resp.content)
            if parsed is not None:
                if schema:
                    import jsonschema
                    try:
                        jsonschema.validate(parsed, schema)
                    except jsonschema.ValidationError as e:
                        logger.warning("Regex-extracted JSON failed schema: %s", e.message[:100])
                        return {}, False
                return parsed, True
        except Exception:
            pass

        logger.error("complete_json: all 3 tiers failed for %d-char prompt", sum(len(m.get("content","")) for m in messages))
        return {}, False

    @property
    def supports_explicit_cache(self) -> bool:
        """Does this provider need explicit cache_control breakpoints?"""
        model = (self.default_model or "").lower()
        url = (self.base_url or "").lower()
        return "claude" in model or "anthropic" in url
```

- [ ] **Step 4: Populate cached_tokens from API response**

In `_call()`, after parsing `usage`, add:

```python
        cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
        # Anthropic uses different field names
        if not cached:
            cached = usage.get("cache_read_input_tokens", 0)
```

Add `cached_tokens=cached` to the `LLMResponse(...)` constructor call.

Do the same in `stream_complete()` for the final `LLMResponse` construction.

- [ ] **Step 5: Run tests**

Run: `python3 -m pytest tests/test_complete_json.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add odigos/providers/llm.py tests/test_complete_json.py
git commit -m "feat: complete_json() with 3-tier fallback, supports_explicit_cache, cached_tokens"
```

---

### Task 3: Switch Extractor to complete_json()

Replace manual JSON parsing in the extractor with `complete_json()`.

**Files:**
- Modify: `odigos/memory/extractor.py`

- [ ] **Step 1: Replace provider.complete() with provider.complete_json()**

In `extract_knowledge()`, replace the existing LLM call + JSON parsing block (lines 69-91) with:

```python
    try:
        parsed, success = await provider.complete_json(
            [{"role": "user", "content": prompt}],
            max_tokens=500,
            temperature=0.1,
            model=model or None,
        )
        if not success:
            return _EMPTY
        return {
            "entities": parsed.get("entities", []),
            "facts": parsed.get("facts", []),
            "relationships": parsed.get("relationships", []),
        }
    except Exception as e:
        logger.warning("Knowledge extraction failed: %s", e)
        return _EMPTY
```

Remove the manual `json.loads`, markdown fence stripping, and the separate JSONDecodeError handler. `complete_json()` handles all of that.

- [ ] **Step 2: Update tests**

In `tests/test_extractor.py`, the `FakeLLM` class needs a `complete_json()` method. Add it:

```python
    async def complete_json(self, messages, **kwargs):
        resp = await self.complete(messages, **kwargs)
        try:
            import json
            parsed = json.loads(resp.content)
            return parsed, True
        except Exception:
            return {}, False
```

- [ ] **Step 3: Run tests**

Run: `python3 -m pytest tests/test_extractor.py -v`
Expected: All 4 PASS

- [ ] **Step 4: Commit**

```bash
git add odigos/memory/extractor.py tests/test_extractor.py
git commit -m "refactor: extractor uses complete_json() instead of manual JSON parsing"
```

---

### Task 4: Upgrade call_llm and run_prompt for JSON Mode

Pass `response_format` through the shared LLM call infrastructure.

**Files:**
- Modify: `odigos/core/llm_prompt.py`

- [ ] **Step 1: Add response_format to call_llm()**

In `call_llm()`, add `response_format` to the kwargs passed to `provider.complete()`:

```python
async def call_llm(provider, messages, *, model=None, max_tokens=500,
                    temperature=0.5, retries=1, log_name="",
                    response_format=None) -> LLMResponse | None:
```

Pass `response_format=response_format` in the `provider.complete()` call (only if truthy).

- [ ] **Step 2: Add response_format to run_prompt()**

In `run_prompt()`, add `response_format=None` parameter and pass it to `call_llm()`.

- [ ] **Step 3: Run tests**

Run: `python3 -m pytest tests/ -q --ignore=tests/test_relevance.py 2>&1 | tail -10`
Expected: No regressions

- [ ] **Step 4: Commit**

```bash
git add odigos/core/llm_prompt.py
git commit -m "feat: call_llm and run_prompt support response_format passthrough"
```

---

### Task 5: Static-First Prompt Ordering + Parallel Tool Instruction

Reorder `build_planned()` for cache optimization and add the parallel tool call hint.

**Files:**
- Modify: `odigos/core/context.py`

- [ ] **Step 1: Add parallel tool instruction to _TOOL_INSTRUCTION**

Append to the existing `_TOOL_INSTRUCTION` string:

```python
    " When you need to call multiple tools that don't depend on each other, "
    "call them all in a single response rather than one at a time."
```

- [ ] **Step 2: Reorder build_planned() assembly**

Change the parts assembly order in `build_planned()` from:

```
identity → tool_instruction → experiences → user_facts → user_profile → rag → history → skill → response_style
```

To (static first):

```
identity → tool_instruction → response_style → skill → experiences → user_facts → user_profile → rag → history
```

Move `response_style` and `skill` up before the dynamic sections. The budget gating logic stays the same — just the order changes.

- [ ] **Step 3: Sort tool definitions alphabetically**

In the tools list assembly section of `build_planned()`, after collecting all tools, sort them by name:

```python
tools = sorted(tools, key=lambda t: t.get("function", {}).get("name", ""))
```

This prevents cache churn from non-deterministic tool ordering.

- [ ] **Step 4: Add Anthropic cache block formatting**

In the system prompt construction, if the provider supports explicit caching, format the system message with content blocks:

```python
# After assembling system_prompt from parts
if hasattr(self, '_provider') and getattr(self._provider, 'supports_explicit_cache', False):
    # Split at the cache boundary (after static sections)
    static_end = len(identity) + len(_TOOL_INSTRUCTION) + len(style_text) + len(skill_text) + 10  # separators
    static_prefix = system_prompt[:static_end]
    dynamic_suffix = system_prompt[static_end:]
    system_msg = {"role": "system", "content": [
        {"type": "text", "text": static_prefix, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": dynamic_suffix},
    ]}
else:
    system_msg = {"role": "system", "content": system_prompt}
```

The `_provider` reference needs to be passed to `ContextAssembler` — add it to `__init__` and set it from bootstrap.

- [ ] **Step 5: Run tests**

Run: `python3 -m pytest tests/ -q --ignore=tests/test_relevance.py 2>&1 | tail -10`
Expected: No regressions

- [ ] **Step 6: Commit**

```bash
git add odigos/core/context.py
git commit -m "feat: static-first prompt ordering, parallel tool instruction, Anthropic cache blocks"
```

---

### Task 6: Pyramid Expansion in Recall

Add token-budgeted content expansion to the recall path.

**Files:**
- Modify: `odigos/memory/manager.py`
- Create: `tests/test_pyramid_recall.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_pyramid_recall.py`:

1. `test_recall_with_token_budget` — recall with `token_budget=500`. Verify output is under 500 tokens (using len//4 estimate).
2. `test_high_relevance_gets_full_content` — set up a document in `document_text` with 2000 chars. Recall with high-relevance match. Verify the full content appears, not just 500-char preview.
3. `test_low_relevance_stays_summary` — low-relevance result stays at content_preview length.
4. `test_clean_truncation` — full content exceeding budget is truncated at sentence boundary with `[... truncated ...]` marker.
5. `test_strategy_parameter` — `_hybrid_search(strategy="union")` uses set-union instead of RRF.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_pyramid_recall.py -v`
Expected: FAIL

- [ ] **Step 3: Add strategy parameter to _hybrid_search()**

Add `strategy: str = "rrf"` parameter. When `strategy == "union"`, merge results with set-union (D ∪ K) instead of RRF scoring. Keep RRF as default.

- [ ] **Step 4: Add token_budget to recall() and implement pyramid tiers**

Update `recall()` signature:

```python
async def recall(self, query: str, limit: int = 5, token_budget: int = 2000) -> str:
```

After getting ranked results from `_hybrid_search()`, implement:

```python
# Separate high-relevance (Tier 2) from the rest (Tier 1)
EXPANSION_THRESHOLD = 0.4
MAX_EXPANSIONS = 3

tier2_candidates = [r for r in ranked if getattr(r, 'cross_encoder_score', 0) > EXPANSION_THRESHOLD][:MAX_EXPANSIONS]
tier1_results = [r for r in ranked if r not in tier2_candidates]

# Reserve budget for Tier 2 expansions first
tier2_budget = token_budget // 2
tier1_budget = token_budget - tier2_budget

# Load full content for Tier 2 (bulk query)
if tier2_candidates:
    source_ids = [r.source_id for r in tier2_candidates]
    full_texts = await self._bulk_fetch_full_text(source_ids)
    for r in tier2_candidates:
        full = full_texts.get(r.source_id)
        if full:
            r.full_content = _clean_truncate(full, tier2_budget // len(tier2_candidates))

# Format with budget enforcement
return self._format_results(tier1_results, tier2_candidates, entity_context, tier1_budget)
```

- [ ] **Step 5: Implement _bulk_fetch_full_text()**

```python
async def _bulk_fetch_full_text(self, source_ids: list[str]) -> dict[str, str]:
    """Fetch full text for multiple source IDs in one query."""
    if not source_ids or not self.db:
        return {}
    placeholders = ",".join("?" * len(source_ids))
    rows = await self.db.fetch_all(
        f"SELECT document_id, full_text FROM document_text WHERE document_id IN ({placeholders})",
        tuple(source_ids),
    )
    result = {r["document_id"]: r["full_text"] for r in rows}
    # Also try messages table for conversation memories
    missing = [sid for sid in source_ids if sid not in result]
    if missing:
        placeholders2 = ",".join("?" * len(missing))
        msg_rows = await self.db.fetch_all(
            f"SELECT conversation_id, content FROM messages WHERE conversation_id IN ({placeholders2}) ORDER BY created_at",
            tuple(missing),
        )
        for r in msg_rows:
            cid = r["conversation_id"]
            if cid not in result:
                result[cid] = r["content"]
    return result
```

- [ ] **Step 6: Implement _clean_truncate()**

```python
def _clean_truncate(text: str, max_tokens: int) -> str:
    """Truncate at sentence boundary within token budget."""
    max_chars = max_tokens * 4  # rough estimate
    if len(text) <= max_chars:
        return text
    # Find the last sentence boundary before the limit
    truncated = text[:max_chars]
    for sep in ['. ', '.\n', '! ', '!\n', '? ', '?\n']:
        idx = truncated.rfind(sep)
        if idx > max_chars // 2:  # Don't truncate too aggressively
            return truncated[:idx + 1].rstrip() + " [... truncated ...]"
    return truncated.rstrip() + " [... truncated ...]"
```

- [ ] **Step 7: Refactor _format_results() from recall()**

Extract the formatting logic (document knowledge section, conversation history section, entity section) from `recall()` into a `_format_results()` method. This method receives tier1 and tier2 results separately and handles the budget-aware formatting.

- [ ] **Step 8: Run tests**

Run: `python3 -m pytest tests/test_pyramid_recall.py tests/test_memory_manager.py -v`
Expected: All PASS

- [ ] **Step 9: Commit**

```bash
git add odigos/memory/manager.py tests/test_pyramid_recall.py
git commit -m "feat: pyramid expansion in recall — token budget, full content for high relevance"
```

---

### Task 7: Wire Token Budget from Context to Recall

Pass the remaining prompt budget from `build_planned()` to `recall()`.

**Files:**
- Modify: `odigos/core/context.py`

- [ ] **Step 1: Pass token_budget to recall**

In `build_planned()`, where `_load_rag_for_plan()` calls `memory_manager.recall()`, pass the remaining budget:

```python
async def _load_rag_for_plan(self, queries, budget_remaining: int = 2000):
    ...
    raw = await self.memory_manager.recall(
        " ".join(queries), limit=10, token_budget=budget_remaining,
    )
```

Calculate `budget_remaining` from `max_prompt_tokens` minus tokens already consumed by the static sections (identity, tool instruction, response style, skill).

- [ ] **Step 2: Wire provider to ContextAssembler for cache detection**

Add `llm_provider` to `ContextAssembler.__init__()` and store as `self._provider`. Pass from bootstrap where the assembler is constructed.

- [ ] **Step 3: Run tests**

Run: `python3 -m pytest tests/ -q --ignore=tests/test_relevance.py 2>&1 | tail -10`
Expected: No regressions

- [ ] **Step 4: Commit**

```bash
git add odigos/core/context.py odigos/bootstrap.py
git commit -m "feat: wire token budget from context to recall, provider to context assembler"
```

---

### Task 8: Deploy and Smoke Test

Deploy to Bob and verify all four improvements.

- [ ] **Step 1: Push and deploy**

```bash
git push origin main
ssh root@82.25.91.86 "cd /opt/odigos && git fetch origin main && git reset --hard origin/main && chown -R odigos_agent:odigos_agent . && systemctl restart odigos"
```

- [ ] **Step 2: Send a message and check extraction**

Send a message with entities. Verify extraction still works with `complete_json()`:

```bash
ssh root@82.25.91.86 "journalctl -u odigos -n 30 --no-pager | grep -i 'knowledge extraction'"
```

- [ ] **Step 3: Check cached_tokens in logs**

```bash
ssh root@82.25.91.86 "journalctl -u odigos -n 50 --no-pager | grep -i 'cached'"
```

- [ ] **Step 4: Verify prompt ordering**

Check that the system prompt starts with identity + tool instruction (static), not RAG results (dynamic).

- [ ] **Step 5: Verify recall with budget**

Send a document-related query and check that high-relevance results get expanded content.
