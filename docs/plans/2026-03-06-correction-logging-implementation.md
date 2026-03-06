# Correction Logging Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Detect user corrections via inline LLM output, store them with vector embeddings, and inject relevant past corrections into future context.

**Architecture:** New `CorrectionsManager` class stores/retrieves corrections via DB + sqlite-vec. The reflector parses `[CORRECTION]` blocks from LLM responses (same pattern as entity extraction). The prompt builder injects relevant corrections and detection instructions into the system prompt.

**Tech Stack:** Python 3.12, pytest, AsyncMock, aiosqlite, sqlite-vec

---

### Task 1: Create corrections DB migration

**Files:**
- Create: `migrations/007_corrections.sql`
- Test: `tests/test_corrections.py`

**Step 1: Write the failing test**

Create `tests/test_corrections.py`:

```python
import pytest

from odigos.db import Database


@pytest.fixture
async def db(tmp_db_path: str):
    database = Database(tmp_db_path, migrations_dir="migrations")
    await database.initialize()
    yield database
    await database.close()


class TestCorrectionsMigration:
    async def test_corrections_table_exists(self, db: Database):
        """Migration creates the corrections table."""
        await db.execute(
            "INSERT INTO corrections (id, conversation_id, original_response, correction, context, category) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("c1", "conv-1", "I said X", "Should be Y", "talking about Z", "preference"),
        )
        row = await db.fetch_one("SELECT * FROM corrections WHERE id = ?", ("c1",))
        assert row is not None
        assert row["category"] == "preference"
        assert row["applied_count"] == 0
        assert row["timestamp"] is not None
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_corrections.py::TestCorrectionsMigration -v`
Expected: FAIL — `no such table: corrections`

**Step 3: Write the migration**

Create `migrations/007_corrections.sql`:

```sql
CREATE TABLE IF NOT EXISTS corrections (
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

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_corrections.py::TestCorrectionsMigration -v`
Expected: PASS

**Step 5: Commit**

```bash
git add migrations/007_corrections.sql tests/test_corrections.py
git commit -m "feat: add corrections DB migration"
```

---

### Task 2: Create CorrectionsManager with store() and relevant()

**Files:**
- Create: `odigos/memory/corrections.py`
- Modify: `tests/test_corrections.py`

**Step 1: Write the failing tests**

Append to `tests/test_corrections.py`:

```python
from unittest.mock import AsyncMock, MagicMock

from odigos.memory.corrections import CorrectionsManager
from odigos.memory.vectors import VectorMemory, MemoryResult


class TestCorrectionsManager:
    async def test_store_inserts_row_and_embeds(self, db: Database):
        """store() inserts into corrections table and calls VectorMemory.store()."""
        mock_vector = AsyncMock(spec=VectorMemory)
        mock_vector.store = AsyncMock(return_value="vec-1")
        manager = CorrectionsManager(db=db, vector_memory=mock_vector)

        await manager.store(
            conversation_id="conv-1",
            original_response="I scheduled for 8am",
            correction="Never schedule before 10am",
            context="morning scheduling",
            category="preference",
        )

        row = await db.fetch_one(
            "SELECT * FROM corrections WHERE conversation_id = ?", ("conv-1",)
        )
        assert row is not None
        assert row["original_response"] == "I scheduled for 8am"
        assert row["correction"] == "Never schedule before 10am"
        assert row["category"] == "preference"

        # Should have embedded the context for vector search
        mock_vector.store.assert_called_once()
        call_args = mock_vector.store.call_args
        assert "morning scheduling" in call_args[1].get("text", call_args[0][0])
        assert call_args[1].get("source_type", call_args[0][1] if len(call_args[0]) > 1 else None) == "correction"

    async def test_store_includes_correction_in_embedding_text(self, db: Database):
        """The embedded text includes both context and correction for better retrieval."""
        mock_vector = AsyncMock(spec=VectorMemory)
        mock_vector.store = AsyncMock(return_value="vec-1")
        manager = CorrectionsManager(db=db, vector_memory=mock_vector)

        await manager.store(
            conversation_id="conv-1",
            original_response="original",
            correction="do this instead",
            context="the situation",
            category="behavior",
        )

        embedded_text = mock_vector.store.call_args[0][0]
        assert "the situation" in embedded_text
        assert "do this instead" in embedded_text

    async def test_relevant_returns_formatted_corrections(self, db: Database):
        """relevant() returns formatted string of matching corrections."""
        mock_vector = AsyncMock(spec=VectorMemory)
        mock_vector.search = AsyncMock(return_value=[
            MemoryResult(
                content_preview="scheduling: Never schedule before 10am",
                source_type="correction",
                source_id="c1",
                distance=0.1,
            ),
        ])
        manager = CorrectionsManager(db=db, vector_memory=mock_vector)

        # Insert the correction that the vector search will find
        await db.execute(
            "INSERT INTO corrections (id, conversation_id, original_response, correction, context, category) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("c1", "conv-1", "I scheduled for 8am", "Never schedule before 10am", "scheduling", "preference"),
        )

        result = await manager.relevant("schedule a meeting at 9am")
        assert "Never schedule before 10am" in result
        assert "preference" in result

    async def test_relevant_returns_empty_when_no_matches(self, db: Database):
        """relevant() returns empty string when no corrections match."""
        mock_vector = AsyncMock(spec=VectorMemory)
        mock_vector.search = AsyncMock(return_value=[])
        manager = CorrectionsManager(db=db, vector_memory=mock_vector)

        result = await manager.relevant("unrelated query")
        assert result == ""

    async def test_relevant_filters_non_correction_results(self, db: Database):
        """relevant() ignores vector results that aren't source_type='correction'."""
        mock_vector = AsyncMock(spec=VectorMemory)
        mock_vector.search = AsyncMock(return_value=[
            MemoryResult(
                content_preview="some entity memory",
                source_type="entity",
                source_id="e1",
                distance=0.05,
            ),
        ])
        manager = CorrectionsManager(db=db, vector_memory=mock_vector)

        result = await manager.relevant("some query")
        assert result == ""
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_corrections.py::TestCorrectionsManager -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'odigos.memory.corrections'`

**Step 3: Write the implementation**

Create `odigos/memory/corrections.py`:

```python
from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.db import Database
    from odigos.memory.vectors import VectorMemory

logger = logging.getLogger(__name__)


class CorrectionsManager:
    """Stores and retrieves user corrections via DB + vector similarity search."""

    def __init__(self, db: Database, vector_memory: VectorMemory) -> None:
        self.db = db
        self.vector_memory = vector_memory

    async def store(
        self,
        conversation_id: str,
        original_response: str,
        correction: str,
        context: str,
        category: str,
    ) -> str:
        """Store a correction in the DB and embed its context for vector search.

        Returns the correction ID.
        """
        correction_id = str(uuid.uuid4())
        await self.db.execute(
            "INSERT INTO corrections (id, conversation_id, original_response, "
            "correction, context, category) VALUES (?, ?, ?, ?, ?, ?)",
            (correction_id, conversation_id, original_response, correction, context, category),
        )

        # Embed context + correction together for better semantic retrieval
        embed_text = f"{context}: {correction}"
        await self.vector_memory.store(embed_text, "correction", correction_id)

        logger.info(
            "Stored correction %s (category=%s) for conversation %s",
            correction_id, category, conversation_id,
        )
        return correction_id

    async def relevant(self, query: str, limit: int = 5) -> str:
        """Find corrections relevant to the query via vector similarity search.

        Returns a formatted string for prompt injection, or empty string if none found.
        """
        results = await self.vector_memory.search(query, limit=limit)

        # Filter to correction source type only
        correction_ids = [
            r.source_id for r in results if r.source_type == "correction"
        ]
        if not correction_ids:
            return ""

        # Fetch full correction records from DB
        placeholders = ",".join("?" for _ in correction_ids)
        rows = await self.db.fetch_all(
            f"SELECT correction, category, context FROM corrections "
            f"WHERE id IN ({placeholders})",
            tuple(correction_ids),
        )

        if not rows:
            return ""

        lines = ["## Learned corrections", "Apply these lessons from past feedback:"]
        for row in rows:
            lines.append(
                f"- [{row['category']}] {row['correction']} (context: {row['context']})"
            )
        return "\n".join(lines)
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_corrections.py -v`
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add odigos/memory/corrections.py tests/test_corrections.py
git commit -m "feat: add CorrectionsManager with store() and relevant()"
```

---

### Task 3: Extend system prompt with correction detection instructions and learned corrections

**Files:**
- Modify: `odigos/personality/prompt_builder.py:11-50`
- Modify: `odigos/core/context.py:44-81`
- Test: `tests/test_prompt_builder.py`

**Step 1: Write the failing tests**

Create or append to `tests/test_prompt_builder.py`:

```python
import pytest

from odigos.personality.loader import Personality, Identity, Voice
from odigos.personality.prompt_builder import build_system_prompt


def _make_personality() -> Personality:
    return Personality(
        name="TestBot",
        identity=Identity(
            role="test assistant",
            relationship="helper",
            first_person=True,
            expresses_uncertainty=True,
            expresses_opinions=True,
        ),
        voice=Voice(
            tone="friendly",
            verbosity="concise",
            humor="light",
            formality="casual",
        ),
    )


class TestCorrectionsInPrompt:
    def test_corrections_section_included_when_provided(self):
        """Corrections context appears in system prompt when non-empty."""
        personality = _make_personality()
        corrections = "## Learned corrections\n- [preference] Never schedule before 10am"
        prompt = build_system_prompt(personality=personality, corrections_context=corrections)
        assert "Learned corrections" in prompt
        assert "Never schedule before 10am" in prompt

    def test_corrections_section_omitted_when_empty(self):
        """No corrections section when corrections_context is empty."""
        personality = _make_personality()
        prompt = build_system_prompt(personality=personality, corrections_context="")
        assert "Learned corrections" not in prompt

    def test_correction_detection_instructions_always_present(self):
        """Correction detection block is always in the system prompt."""
        personality = _make_personality()
        prompt = build_system_prompt(personality=personality)
        assert "[CORRECTION]" in prompt
        assert "[/CORRECTION]" in prompt

    def test_corrections_appear_before_entity_extraction(self):
        """Corrections section comes before entity extraction instruction."""
        personality = _make_personality()
        corrections = "## Learned corrections\n- [preference] Test correction"
        prompt = build_system_prompt(personality=personality, corrections_context=corrections)
        corrections_pos = prompt.index("Learned corrections")
        entity_pos = prompt.index("<!--entities")
        assert corrections_pos < entity_pos
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_prompt_builder.py::TestCorrectionsInPrompt -v`
Expected: FAIL — `build_system_prompt()` does not accept `corrections_context` parameter.

**Step 3: Write the implementation**

Modify `odigos/personality/prompt_builder.py`:

1. Add `CORRECTION_DETECTION_INSTRUCTION` constant after `ENTITY_EXTRACTION_INSTRUCTION`:

```python
CORRECTION_DETECTION_INSTRUCTION = """If the user's message is correcting or disagreeing with your previous response, include a correction block after your response in this exact format:
<!--correction
{"original": "brief summary of what you said wrong", "correction": "what the user wants instead", "category": "tone|accuracy|preference|behavior|tool_choice", "context": "brief description of the situation"}
-->
Only include this block when the user is explicitly correcting you. Categories:
- tone: communication style (too formal, too casual, etc.)
- accuracy: factual errors
- preference: user preferences (scheduling, formatting, etc.)
- behavior: action/decision patterns
- tool_choice: wrong tool or approach used
If the user is not correcting you, omit the block entirely."""
```

2. Add `corrections_context` parameter to `build_system_prompt()`:

```python
def build_system_prompt(
    personality: Personality,
    memory_context: str = "",
    tool_context: str = "",
    skill_catalog: str = "",
    corrections_context: str = "",
) -> str:
```

3. Add corrections sections (after skill_catalog, before entity extraction):

```python
    # 6. Learned corrections (optional)
    if corrections_context:
        sections.append(corrections_context)

    # 7. Correction detection (always)
    sections.append(CORRECTION_DETECTION_INSTRUCTION)

    # 8. Entity extraction (always)
    sections.append(ENTITY_EXTRACTION_INSTRUCTION)
```

Update the docstring section numbers accordingly.

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_prompt_builder.py -v`
Expected: All tests PASS.

**Step 5: Wire corrections into ContextAssembler**

Modify `odigos/core/context.py`:

1. Add `CorrectionsManager` to TYPE_CHECKING imports:

```python
if TYPE_CHECKING:
    from odigos.memory.corrections import CorrectionsManager
    from odigos.memory.manager import MemoryManager
    from odigos.memory.summarizer import ConversationSummarizer
    from odigos.skills.registry import SkillRegistry
```

2. Add `corrections_manager` parameter to `__init__()`:

```python
    def __init__(
        self,
        db: Database,
        agent_name: str,
        history_limit: int = 20,
        memory_manager: MemoryManager | None = None,
        personality_path: str = "data/personality.yaml",
        summarizer: ConversationSummarizer | None = None,
        skill_registry: SkillRegistry | None = None,
        corrections_manager: CorrectionsManager | None = None,
    ) -> None:
        # ... existing assignments ...
        self.corrections_manager = corrections_manager
```

3. In `build()`, after memory recall and before `build_system_prompt()`:

```python
        # Get relevant corrections if available
        corrections_context = ""
        if self.corrections_manager:
            corrections_context = await self.corrections_manager.relevant(current_message)

        # Build system prompt via structured prompt builder
        system_prompt = build_system_prompt(
            personality=personality,
            memory_context=memory_context,
            tool_context=tool_context,
            skill_catalog=skill_catalog,
            corrections_context=corrections_context,
        )
```

**Step 6: Run all tests**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: All tests PASS (existing tests should still work since `corrections_context` defaults to `""`).

**Step 7: Commit**

```bash
git add odigos/personality/prompt_builder.py odigos/core/context.py tests/test_prompt_builder.py
git commit -m "feat: add correction detection and learned corrections to system prompt"
```

---

### Task 4: Extend Reflector to parse [CORRECTION] blocks

**Files:**
- Modify: `odigos/core/reflector.py:1-55`
- Test: `tests/test_corrections.py`

**Step 1: Write the failing tests**

Append to `tests/test_corrections.py`:

```python
from odigos.core.reflector import Reflector
from odigos.memory.corrections import CorrectionsManager
from odigos.providers.base import LLMResponse


async def _seed_conversation(db: Database, conversation_id: str) -> None:
    await db.execute(
        "INSERT INTO conversations (id, channel) VALUES (?, ?)",
        (conversation_id, "test"),
    )


class TestReflectorCorrectionParsing:
    async def test_correction_block_parsed_and_stored(self, db: Database):
        """Reflector parses <!--correction ... --> blocks and calls CorrectionsManager.store()."""
        await _seed_conversation(db, "conv-1")

        mock_corrections = AsyncMock(spec=CorrectionsManager)
        mock_corrections.store = AsyncMock()

        reflector = Reflector(db, corrections_manager=mock_corrections)

        content = (
            'Here is the corrected answer.\n'
            '<!--correction\n'
            '{"original": "I said 8am", "correction": "Never before 10am", '
            '"category": "preference", "context": "morning scheduling"}\n'
            '-->'
        )
        response = LLMResponse(
            content=content, model="test", tokens_in=10, tokens_out=20, cost_usd=0.0,
        )
        await reflector.reflect("conv-1", response)

        mock_corrections.store.assert_called_once_with(
            conversation_id="conv-1",
            original_response="I said 8am",
            correction="Never before 10am",
            context="morning scheduling",
            category="preference",
        )

    async def test_correction_block_stripped_from_stored_content(self, db: Database):
        """The <!--correction --> block is removed from the message stored in DB."""
        await _seed_conversation(db, "conv-1")

        mock_corrections = AsyncMock(spec=CorrectionsManager)
        mock_corrections.store = AsyncMock()

        reflector = Reflector(db, corrections_manager=mock_corrections)

        content = (
            'Here is the corrected answer.\n'
            '<!--correction\n'
            '{"original": "X", "correction": "Y", "category": "accuracy", "context": "Z"}\n'
            '-->'
        )
        response = LLMResponse(
            content=content, model="test", tokens_in=10, tokens_out=20, cost_usd=0.0,
        )
        await reflector.reflect("conv-1", response)

        row = await db.fetch_one(
            "SELECT content FROM messages WHERE conversation_id = ? AND role = 'assistant'",
            ("conv-1",),
        )
        assert "<!--correction" not in row["content"]
        assert "Here is the corrected answer." in row["content"]

    async def test_no_correction_block_no_store_call(self, db: Database):
        """When there's no correction block, CorrectionsManager.store() is not called."""
        await _seed_conversation(db, "conv-1")

        mock_corrections = AsyncMock(spec=CorrectionsManager)
        reflector = Reflector(db, corrections_manager=mock_corrections)

        response = LLMResponse(
            content="Just a normal response.", model="test",
            tokens_in=10, tokens_out=20, cost_usd=0.0,
        )
        await reflector.reflect("conv-1", response)

        mock_corrections.store.assert_not_called()

    async def test_malformed_correction_json_handled_gracefully(self, db: Database):
        """Malformed JSON in correction block is logged but doesn't crash."""
        await _seed_conversation(db, "conv-1")

        mock_corrections = AsyncMock(spec=CorrectionsManager)
        reflector = Reflector(db, corrections_manager=mock_corrections)

        content = 'Answer.\n<!--correction\n{bad json}\n-->'
        response = LLMResponse(
            content=content, model="test", tokens_in=10, tokens_out=20, cost_usd=0.0,
        )
        await reflector.reflect("conv-1", response)

        mock_corrections.store.assert_not_called()
        # Message should still be stored (with correction block stripped)
        row = await db.fetch_one(
            "SELECT content FROM messages WHERE conversation_id = ?", ("conv-1",),
        )
        assert row is not None
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_corrections.py::TestReflectorCorrectionParsing -v`
Expected: FAIL — `Reflector.__init__()` does not accept `corrections_manager` parameter.

**Step 3: Write the implementation**

Modify `odigos/core/reflector.py`:

1. Add `CORRECTION_PATTERN` after `ENTITY_PATTERN`:

```python
CORRECTION_PATTERN = re.compile(r"<!--correction\s*\n(.*?)\n-->", re.DOTALL)
```

2. Add TYPE_CHECKING import for `CorrectionsManager`:

```python
if TYPE_CHECKING:
    from odigos.memory.corrections import CorrectionsManager
    from odigos.memory.manager import MemoryManager
```

3. Add `corrections_manager` parameter to `__init__()`:

```python
    def __init__(
        self,
        db: Database,
        memory_manager: MemoryManager | None = None,
        cost_fetcher: Callable | None = None,
        corrections_manager: CorrectionsManager | None = None,
    ) -> None:
        self.db = db
        self.memory_manager = memory_manager
        self._cost_fetcher = cost_fetcher
        self.corrections_manager = corrections_manager
```

4. In `reflect()`, after entity parsing and before storing the message, add correction parsing:

```python
        # Parse and strip correction block
        correction_match = CORRECTION_PATTERN.search(content)
        if correction_match:
            try:
                correction_data = json.loads(correction_match.group(1))
                if self.corrections_manager:
                    await self.corrections_manager.store(
                        conversation_id=conversation_id,
                        original_response=correction_data["original"],
                        correction=correction_data["correction"],
                        context=correction_data.get("context", ""),
                        category=correction_data.get("category", "behavior"),
                    )
            except (json.JSONDecodeError, KeyError):
                logger.warning("Failed to parse correction block from response")
            content = CORRECTION_PATTERN.sub("", content).rstrip()
```

Place this after the entity extraction parsing (which already strips `<!--entities -->` blocks) and before the `INSERT INTO messages` statement.

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_corrections.py -v`
Expected: All tests PASS.

**Step 5: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: All tests PASS (existing reflector tests still work since `corrections_manager` defaults to `None`).

**Step 6: Commit**

```bash
git add odigos/core/reflector.py tests/test_corrections.py
git commit -m "feat: parse correction blocks in reflector and store via CorrectionsManager"
```

---

### Task 5: Wire CorrectionsManager into Agent and main.py

**Files:**
- Modify: `odigos/core/agent.py:27-71`
- Modify: `odigos/main.py`

**Step 1: Wire into Agent**

In `odigos/core/agent.py`:

1. Add TYPE_CHECKING import:

```python
if TYPE_CHECKING:
    from odigos.core.budget import BudgetTracker
    from odigos.memory.corrections import CorrectionsManager
    from odigos.memory.manager import MemoryManager
    from odigos.memory.summarizer import ConversationSummarizer
    from odigos.skills.registry import SkillRegistry
    from odigos.tools.registry import ToolRegistry
```

2. Add `corrections_manager` parameter to `__init__()`:

```python
    def __init__(
        self,
        db: Database,
        provider: LLMProvider,
        agent_name: str = "Odigos",
        history_limit: int = 20,
        memory_manager: MemoryManager | None = None,
        personality_path: str = "data/personality.yaml",
        tool_registry: ToolRegistry | None = None,
        skill_registry: SkillRegistry | None = None,
        cost_fetcher: Callable | None = None,
        budget_tracker: BudgetTracker | None = None,
        max_tool_turns: int = 25,
        run_timeout: int = 300,
        summarizer: ConversationSummarizer | None = None,
        corrections_manager: CorrectionsManager | None = None,
    ) -> None:
```

3. Pass `corrections_manager` to `ContextAssembler`:

```python
        self.context_assembler = ContextAssembler(
            db,
            agent_name,
            history_limit,
            memory_manager=memory_manager,
            personality_path=personality_path,
            summarizer=summarizer,
            skill_registry=skill_registry,
            corrections_manager=corrections_manager,
        )
```

4. Pass `corrections_manager` to `Reflector`:

```python
        self.reflector = Reflector(
            db,
            memory_manager=memory_manager,
            cost_fetcher=cost_fetcher,
            corrections_manager=corrections_manager,
        )
```

**Step 2: Wire into main.py**

In `odigos/main.py`, after `memory_manager` is created and before `agent = Agent(...)`:

```python
    # Initialize corrections manager
    from odigos.memory.corrections import CorrectionsManager

    corrections_manager = CorrectionsManager(db=_db, vector_memory=vector_memory)
    logger.info("Corrections manager initialized")
```

Pass to Agent constructor:

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
        corrections_manager=corrections_manager,
    )
```

**Step 3: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: All tests PASS.

**Step 4: Commit**

```bash
git add odigos/core/agent.py odigos/main.py
git commit -m "feat: wire CorrectionsManager into Agent, Reflector, ContextAssembler, and main.py"
```

---

### Task 6: End-to-end test

**Files:**
- Modify: `tests/test_corrections.py`

**Step 1: Write the end-to-end test**

Append to `tests/test_corrections.py`:

```python
class TestCorrectionsEndToEnd:
    async def test_correction_stored_and_retrieved_in_context(self, db: Database):
        """Full flow: store a correction, then verify it appears in relevant() output."""
        mock_vector = AsyncMock(spec=VectorMemory)

        # store() embeds and returns an ID
        mock_vector.store = AsyncMock(return_value="vec-1")

        manager = CorrectionsManager(db=db, vector_memory=mock_vector)

        # Store a correction
        correction_id = await manager.store(
            conversation_id="conv-1",
            original_response="I scheduled for 8am",
            correction="Never schedule before 10am",
            context="morning scheduling",
            category="preference",
        )

        # Now simulate vector search returning this correction
        mock_vector.search = AsyncMock(return_value=[
            MemoryResult(
                content_preview="morning scheduling: Never schedule before 10am",
                source_type="correction",
                source_id=correction_id,
                distance=0.1,
            ),
        ])

        # Retrieve relevant corrections
        result = await manager.relevant("schedule meeting at 9am")

        assert "Learned corrections" in result
        assert "Never schedule before 10am" in result
        assert "preference" in result
        assert "morning scheduling" in result
```

**Step 2: Run the test**

Run: `.venv/bin/python -m pytest tests/test_corrections.py::TestCorrectionsEndToEnd -v`
Expected: PASS

**Step 3: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: All tests PASS.

**Step 4: Commit**

```bash
git add tests/test_corrections.py
git commit -m "test: add end-to-end correction storage and retrieval test"
```
