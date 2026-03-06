# Context Compaction Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Wire the existing ConversationSummarizer into ContextAssembler so old messages are summarized before being discarded.

**Architecture:** ContextAssembler calls `summarizer.summarize_if_needed()` on each `build()`, then fetches any existing summaries and prepends them as a system message between the system prompt and history. Token budget trimming drops oldest summaries first, then oldest history.

**Tech Stack:** Python 3.12, asyncio, aiosqlite

---

### Task 1: Wire summarizer into ContextAssembler and inject summaries

**Files:**
- Modify: `odigos/core/context.py`
- Test: `tests/test_core.py`

**Step 1: Write the failing tests**

Add to `tests/test_core.py`:

```python
class TestContextCompaction:
    async def test_summaries_injected_into_context(self, db: Database):
        """Existing conversation summaries appear between system prompt and history."""
        mock_summarizer = AsyncMock()
        mock_summarizer.summarize_if_needed = AsyncMock()

        assembler = ContextAssembler(
            db=db,
            agent_name="TestBot",
            history_limit=20,
            personality_path="/nonexistent",
            summarizer=mock_summarizer,
        )

        # Insert a conversation and a summary
        await db.execute(
            "INSERT INTO conversations (id, channel) VALUES (?, ?)",
            ("conv-compact", "test"),
        )
        await db.execute(
            "INSERT INTO conversation_summaries (id, conversation_id, start_message_idx, end_message_idx, summary) "
            "VALUES (?, ?, ?, ?, ?)",
            ("sum-1", "conv-compact", 0, 10, "User discussed Python projects."),
        )
        await db.execute(
            "INSERT INTO messages (id, conversation_id, role, content) VALUES (?, ?, ?, ?)",
            ("msg-1", "conv-compact", "user", "Recent message"),
        )

        messages = await assembler.build("conv-compact", "Hello")

        # system + summary + 1 history + current = 4
        assert len(messages) == 4
        assert messages[0]["role"] == "system"  # system prompt
        assert messages[1]["role"] == "system"  # summary
        assert "Python projects" in messages[1]["content"]
        assert messages[2]["content"] == "Recent message"  # history
        assert messages[3]["content"] == "Hello"  # current

        mock_summarizer.summarize_if_needed.assert_called_once_with("conv-compact")

    async def test_no_summarizer_still_works(self, db: Database):
        """Without summarizer, context assembler works as before."""
        assembler = ContextAssembler(
            db=db,
            agent_name="TestBot",
            history_limit=20,
            personality_path="/nonexistent",
        )

        messages = await assembler.build("conv-1", "Hello")
        assert messages[0]["role"] == "system"
        assert messages[-1]["content"] == "Hello"

    async def test_summary_trimmed_before_history(self, db: Database):
        """When over token budget, summaries are trimmed before history."""
        assembler = ContextAssembler(
            db=db,
            agent_name="TestBot",
            history_limit=20,
            personality_path="/nonexistent",
        )

        await db.execute(
            "INSERT INTO conversations (id, channel) VALUES (?, ?)",
            ("conv-trim", "test"),
        )
        # Insert a very long summary
        await db.execute(
            "INSERT INTO conversation_summaries (id, conversation_id, start_message_idx, end_message_idx, summary) "
            "VALUES (?, ?, ?, ?, ?)",
            ("sum-1", "conv-trim", 0, 10, "x" * 8000),
        )
        await db.execute(
            "INSERT INTO messages (id, conversation_id, role, content) VALUES (?, ?, ?, ?)",
            ("msg-1", "conv-trim", "user", "Keep me"),
        )

        messages = await assembler.build("conv-trim", "Hello", max_tokens=500)

        # Summary should be trimmed, history and current kept
        contents = [m["content"] for m in messages]
        assert any("Keep me" in c for c in contents)
        assert not any("x" * 100 in c for c in contents)
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_core.py::TestContextCompaction -v`
Expected: FAIL (ContextAssembler doesn't accept `summarizer` yet)

**Step 3: Implement context compaction in ContextAssembler**

Modify `odigos/core/context.py`:

1. Add `summarizer` parameter to `__init__` (optional, defaults to `None`)
2. Add TYPE_CHECKING import for `ConversationSummarizer`
3. In `build()`:
   - Call `summarizer.summarize_if_needed(conversation_id)` if summarizer exists
   - Fetch summaries from `conversation_summaries` table
   - If summaries exist, concatenate into one system message and insert after system prompt
4. In `_trim_to_budget()`:
   - Identify summary messages (they have `[Previous conversation summary]` prefix)
   - Trim summary messages first (oldest), then history messages

The updated `build()` method:

```python
async def build(
    self,
    conversation_id: str,
    current_message: str,
    tool_context: str = "",
    max_tokens: int = 0,
) -> list[dict]:
    messages: list[dict] = []

    # Trigger summarization of old messages if needed
    if self.summarizer:
        try:
            await self.summarizer.summarize_if_needed(conversation_id)
        except Exception:
            logger.debug("Summarization failed", exc_info=True)

    # Load personality and build system prompt (unchanged)
    personality = load_personality(self.personality_path)
    memory_context = ""
    if self.memory_manager:
        memory_context = await self.memory_manager.recall(current_message)
    system_prompt = build_system_prompt(
        personality=personality,
        memory_context=memory_context,
        tool_context=tool_context,
    )
    messages.append({"role": "system", "content": system_prompt})

    # Fetch and inject conversation summaries
    summaries = await self.db.fetch_all(
        "SELECT summary FROM conversation_summaries "
        "WHERE conversation_id = ? ORDER BY start_message_idx ASC",
        (conversation_id,),
    )
    if summaries:
        combined = "\n\n".join(s["summary"] for s in summaries)
        messages.append({
            "role": "system",
            "content": f"[Previous conversation summary]:\n\n{combined}",
        })

    # Conversation history (unchanged)
    history = await self.db.fetch_all(
        "SELECT role, content FROM messages "
        "WHERE conversation_id = ? ORDER BY timestamp ASC LIMIT ?",
        (conversation_id, self.history_limit),
    )
    for row in history:
        messages.append({"role": row["role"], "content": row["content"]})

    messages.append({"role": "user", "content": current_message})

    if max_tokens > 0:
        messages = self._trim_to_budget(messages, max_tokens)

    return messages
```

The updated `_trim_to_budget()`:

```python
def _trim_to_budget(self, messages: list[dict], max_tokens: int) -> list[dict]:
    total = sum(estimate_tokens(m["content"]) for m in messages)
    if total <= max_tokens:
        return messages

    # Phase 1: trim summary messages first (index 1 if it's a summary)
    while total > max_tokens and len(messages) > 2:
        # Find the first summary message (after system prompt)
        summary_idx = None
        for i in range(1, len(messages) - 1):
            if messages[i].get("content", "").startswith("[Previous conversation summary]"):
                summary_idx = i
                break

        if summary_idx is not None:
            removed = messages.pop(summary_idx)
            total -= estimate_tokens(removed["content"])
            logger.debug("Trimmed summary message to fit context budget")
        else:
            # Phase 2: trim oldest history messages
            removed = messages.pop(1)
            total -= estimate_tokens(removed["content"])
            logger.debug("Trimmed history message to fit context budget")

    if total > max_tokens:
        logger.warning(
            "Context still over budget after trimming all history (%d > %d tokens)",
            total, max_tokens,
        )

    return messages
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_core.py::TestContextCompaction -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `.venv/bin/python -m pytest -v --tb=short`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add odigos/core/context.py tests/test_core.py
git commit -m "feat: wire summarizer into context assembler for compaction"
```

---

### Task 2: Thread summarizer through Agent and main.py

**Files:**
- Modify: `odigos/core/agent.py`
- Modify: `odigos/main.py`
- Test: `tests/test_core.py` (existing tests still pass)

**Step 1: Update Agent to accept and pass summarizer**

In `odigos/core/agent.py`:
- Add `summarizer` parameter to `__init__` (optional, `None`)
- Add TYPE_CHECKING import for `ConversationSummarizer`
- Pass it to `ContextAssembler`

```python
# In TYPE_CHECKING block, add:
from odigos.memory.summarizer import ConversationSummarizer

# In __init__, add parameter:
summarizer: ConversationSummarizer | None = None,

# Pass to ContextAssembler:
self.context_assembler = ContextAssembler(
    db,
    agent_name,
    history_limit,
    memory_manager=memory_manager,
    personality_path=personality_path,
    summarizer=summarizer,
)
```

**Step 2: Update main.py to pass summarizer to Agent**

In `odigos/main.py`, the `summarizer` is already created at line 95. Add it to the Agent initialization:

```python
agent = Agent(
    db=_db,
    provider=_router,
    agent_name=settings.agent.name,
    memory_manager=memory_manager,
    personality_path=settings.personality.path,
    tool_registry=tool_registry,
    skill_registry=skill_registry,
    cost_fetcher=_delayed_cost_fetcher,
    budget_tracker=budget_tracker,
    max_tool_turns=settings.agent.max_tool_turns,
    run_timeout=settings.agent.run_timeout_seconds,
    summarizer=summarizer,
)
```

**Step 3: Run full test suite**

Run: `.venv/bin/python -m pytest -v --tb=short`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add odigos/core/agent.py odigos/main.py
git commit -m "feat: thread summarizer through Agent to enable context compaction"
```

---

### Verification

After both tasks:
- `ContextAssembler` calls `summarize_if_needed()` on each build
- Summaries appear in context between system prompt and history
- Token budget trims summaries first, then history
- All existing tests still pass (backward compatible via optional params)
- Summarizer is wired end-to-end in main.py
