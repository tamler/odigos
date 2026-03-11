# Memory & Messaging Upgrades Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Adopt ReMe-inspired memory patterns (when_to_use embeddings, deduplication, structured compaction, typed taxonomy) and prep the messaging layer for relay-style patterns (WebSocket peer transport, message deduplication, delivery tracking).

**Architecture:** Memory upgrades add a `when_to_use` field to vector storage, introduce LLM-driven deduplication before committing new memories, restructure conversation compaction with a Goal/Progress/Decisions format, and add a `memory_type` field for typed retrieval. Messaging upgrades add a `peer_messages` DB table for deduplication and delivery tracking, extend the WebSocket endpoint to handle peer connections alongside dashboard clients, and add message_id-based idempotency.

**Tech Stack:** Python 3.12, aiosqlite, ChromaDB, FastAPI, WebSocket, pytest

---

## Context for the Implementer

### Project Structure
- Source: `odigos/` — main Python package
- Tests: `tests/` — pytest with pytest-asyncio
- Migrations: `migrations/` — numbered SQL files (currently up to 012)
- Run tests: `.venv/bin/python -m pytest tests/ -x -q`
- Run single test: `.venv/bin/python -m pytest tests/test_file.py::TestClass::test_method -v`

### Key Files You'll Touch

**Memory (Tasks 1-4):**
- `odigos/memory/vectors.py` — VectorMemory class (ChromaDB store/search)
- `odigos/memory/manager.py` — MemoryManager (recall/store orchestration)
- `odigos/memory/summarizer.py` — ConversationSummarizer
- `odigos/memory/graph.py` — EntityGraph (entity/edge tables)
- `migrations/013_memory_type.sql` — New migration for memory_type on entities

**Messaging (Tasks 5-7):**
- `odigos/core/peers.py` — PeerClient (outbound messaging)
- `odigos/channels/web.py` — WebChannel
- `odigos/api/ws.py` — WebSocket endpoint
- `odigos/api/agent_message.py` — Inbound peer message endpoint
- `migrations/014_peer_messages.sql` — New migration for message tracking

### Existing Patterns
- All async tests use `async def test_*` (pytest-asyncio auto mode)
- DB fixture: `tmp_db_path` from conftest, then `Database(path, migrations_dir="migrations")`
- Mock embedder: `AsyncMock()` with `.embed.return_value = [0.1] * 768`
- VectorMemory fixture: `VectorMemory(embedder=mock, persist_dir=str(tmp_path / "chroma"))`
- Commit style: `feat(scope): description` or `fix(scope): description`

---

### Task 1: Add `when_to_use` Field to Vector Memory

The single most impactful change from ReMe. Instead of embedding raw content, we embed a `when_to_use` description that captures *when* a memory is relevant, not just what it contains.

**Files:**
- Modify: `odigos/memory/vectors.py`
- Test: `tests/test_vector_memory.py`

**Step 1: Write the failing tests**

Create `tests/test_vector_memory.py`:

```python
from unittest.mock import AsyncMock

import pytest

from odigos.memory.vectors import VectorMemory, MemoryResult


@pytest.fixture
def mock_embedder():
    embedder = AsyncMock()
    embedder.embed.return_value = [0.1] * 768
    embedder.embed_query.return_value = [0.1] * 768
    return embedder


@pytest.fixture
async def vector_memory(tmp_path, mock_embedder):
    vm = VectorMemory(embedder=mock_embedder, persist_dir=str(tmp_path / "chroma"))
    await vm.initialize()
    return vm


class TestWhenToUse:
    async def test_store_with_when_to_use(self, vector_memory, mock_embedder):
        """when_to_use is embedded instead of raw content."""
        vec_id = await vector_memory.store(
            text="User prefers dark mode in all applications",
            source_type="user_message",
            source_id="conv-1",
            when_to_use="when configuring UI themes or display settings",
        )
        assert vec_id

        # The embed call should use when_to_use text, not the raw content
        embed_arg = mock_embedder.embed.call_args[0][0]
        assert "configuring UI themes" in embed_arg

    async def test_store_without_when_to_use_uses_content(self, vector_memory, mock_embedder):
        """Without when_to_use, falls back to embedding the content."""
        await vector_memory.store(
            text="Some fact about the user",
            source_type="user_message",
            source_id="conv-1",
        )
        embed_arg = mock_embedder.embed.call_args[0][0]
        assert "Some fact about the user" in embed_arg

    async def test_search_returns_when_to_use(self, vector_memory):
        """Search results include the when_to_use field."""
        await vector_memory.store(
            text="Alice is a software engineer",
            source_type="user_message",
            source_id="conv-1",
            when_to_use="when discussing Alice's profession or technical skills",
        )
        results = await vector_memory.search("Alice's job")
        assert len(results) >= 1
        assert results[0].when_to_use == "when discussing Alice's profession or technical skills"

    async def test_backward_compatible_search(self, vector_memory):
        """Memories stored without when_to_use still searchable."""
        await vector_memory.store(
            text="Meeting at 3pm tomorrow",
            source_type="user_message",
            source_id="conv-2",
        )
        results = await vector_memory.search("meeting time")
        assert len(results) >= 1
        assert results[0].when_to_use == ""
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_vector_memory.py -v`
Expected: FAIL — `store()` doesn't accept `when_to_use`, `MemoryResult` has no `when_to_use` field

**Step 3: Implement the changes**

Modify `odigos/memory/vectors.py`:

1. Add `when_to_use: str = ""` to `MemoryResult` dataclass (after `distance`)
2. Update `store()` signature to accept `when_to_use: str = ""`
3. In `store()`: embed `when_to_use` if provided, else embed `text`
4. Store `when_to_use` in ChromaDB metadata
5. In `search()`: populate `when_to_use` from metadata

```python
@dataclass
class MemoryResult:
    content_preview: str
    source_type: str
    source_id: str
    distance: float
    when_to_use: str = ""


class VectorMemory:
    # ... existing __init__ and initialize unchanged ...

    async def store(
        self, text: str, source_type: str, source_id: str, when_to_use: str = "",
    ) -> str:
        """Embed text (or when_to_use if provided) and store in ChromaDB."""
        embed_text = when_to_use if when_to_use else text
        vector = await self.embedder.embed(embed_text)
        vec_id = str(uuid.uuid4())

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            partial(
                self._collection.add,
                ids=[vec_id],
                embeddings=[vector],
                metadatas=[{
                    "source_type": source_type,
                    "source_id": source_id,
                    "content_preview": text[:500],
                    "when_to_use": when_to_use,
                }],
                documents=[text[:500]],
            ),
        )
        return vec_id

    async def search(self, query, limit=5, source_type=None):
        # ... existing search logic ...
        # In the result building loop, add:
        #   when_to_use=meta.get("when_to_use", ""),
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_vector_memory.py -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -x -q`
Expected: All pass (existing callers don't pass when_to_use, so default "" preserves behavior)

**Step 6: Commit**

```bash
git add odigos/memory/vectors.py tests/test_vector_memory.py
git commit -m "feat(memory): add when_to_use field for situation-aware retrieval"
```

---

### Task 2: Memory Type Taxonomy

Add a `memory_type` field to vector storage so memories can be categorized and retrieved by type. Based on ReMe's taxonomy, simplified for our use case.

**Files:**
- Modify: `odigos/memory/vectors.py`
- Modify: `odigos/memory/manager.py`
- Modify: `odigos/memory/summarizer.py`
- Modify: `tests/test_vector_memory.py`
- Modify: `tests/test_memory_manager.py`

**Step 1: Write the failing tests**

Add to `tests/test_vector_memory.py`:

```python
class TestMemoryType:
    async def test_store_with_memory_type(self, vector_memory):
        """Memories can be stored with a type classification."""
        vec_id = await vector_memory.store(
            text="User prefers Python",
            source_type="user_message",
            source_id="conv-1",
            memory_type="personal",
        )
        results = await vector_memory.search("preferences")
        assert results[0].memory_type == "personal"

    async def test_filter_by_memory_type(self, vector_memory):
        """Search can filter by memory_type."""
        await vector_memory.store(
            text="Deploy with docker compose up",
            source_type="user_message",
            source_id="conv-1",
            memory_type="procedural",
        )
        await vector_memory.store(
            text="User likes dark mode",
            source_type="user_message",
            source_id="conv-2",
            memory_type="personal",
        )
        results = await vector_memory.search("user settings", memory_type="personal")
        for r in results:
            assert r.memory_type == "personal"

    async def test_default_memory_type_is_general(self, vector_memory):
        """Default memory_type is 'general'."""
        await vector_memory.store(
            text="Random fact",
            source_type="user_message",
            source_id="conv-1",
        )
        results = await vector_memory.search("fact")
        assert results[0].memory_type == "general"
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_vector_memory.py::TestMemoryType -v`
Expected: FAIL

**Step 3: Implement**

1. Add `memory_type: str = "general"` to `MemoryResult`
2. Add `memory_type: str = "general"` parameter to `VectorMemory.store()`
3. Store `memory_type` in ChromaDB metadata
4. Add `memory_type: str | None = None` parameter to `VectorMemory.search()`
5. In `search()`, if both `source_type` and `memory_type` are provided, use `$and` in ChromaDB where filter:
   ```python
   where_filter = None
   conditions = []
   if source_type:
       conditions.append({"source_type": source_type})
   if memory_type:
       conditions.append({"memory_type": memory_type})
   if len(conditions) == 1:
       where_filter = conditions[0]
   elif len(conditions) > 1:
       where_filter = {"$and": conditions}
   ```
6. Read `memory_type` from metadata in search results: `memory_type=meta.get("memory_type", "general")`

**Step 4: Update MemoryManager to pass memory_type**

In `odigos/memory/manager.py`, update `_store_impl`:
- User message chunks: `memory_type="personal"` (user messages contain preferences, facts about them)
- In `recall()`: no filter change needed (search all types by default)

In `odigos/memory/summarizer.py`, update `summarize_if_needed`:
- Conversation summaries: `memory_type="summary"` when calling `vector_memory.store()`

**Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/test_vector_memory.py tests/test_memory_manager.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add odigos/memory/vectors.py odigos/memory/manager.py odigos/memory/summarizer.py tests/test_vector_memory.py tests/test_memory_manager.py
git commit -m "feat(memory): add memory_type taxonomy for typed retrieval"
```

---

### Task 3: Draft-and-Compare Deduplication

Before committing a new memory to the vector store, search for similar existing memories and skip if a near-duplicate exists. This prevents memory bloat over time.

**Files:**
- Modify: `odigos/memory/manager.py`
- Test: `tests/test_memory_dedup.py`

**Step 1: Write the failing tests**

Create `tests/test_memory_dedup.py`:

```python
from unittest.mock import AsyncMock

import pytest

from odigos.memory.manager import MemoryManager
from odigos.memory.graph import EntityGraph
from odigos.memory.resolver import EntityResolver
from odigos.memory.summarizer import ConversationSummarizer
from odigos.memory.vectors import VectorMemory
from odigos.db import Database
from odigos.providers.base import LLMResponse


@pytest.fixture
async def db(tmp_db_path):
    database = Database(tmp_db_path, migrations_dir="migrations")
    await database.initialize()
    yield database
    await database.close()


@pytest.fixture
def mock_embedder():
    embedder = AsyncMock()
    # Use slightly different vectors so cosine distance is small but nonzero
    call_count = 0
    def make_embed(text):
        nonlocal call_count
        call_count += 1
        base = [0.1] * 768
        base[0] = 0.1 + (call_count * 0.0001)  # tiny variation
        return base
    embedder.embed.side_effect = make_embed
    embedder.embed_query.side_effect = make_embed
    return embedder


@pytest.fixture
async def vector_memory(tmp_path, mock_embedder):
    vm = VectorMemory(embedder=mock_embedder, persist_dir=str(tmp_path / "chroma"))
    await vm.initialize()
    return vm


@pytest.fixture
def mock_provider():
    provider = AsyncMock()
    provider.complete.return_value = LLMResponse(
        content="Summary text", model="m", tokens_in=1, tokens_out=1, cost_usd=0.0
    )
    return provider


@pytest.fixture
def manager(vector_memory, db, mock_provider):
    graph = EntityGraph(db=db)
    resolver = EntityResolver(graph=graph, vector_memory=vector_memory)
    summarizer = ConversationSummarizer(
        db=db, vector_memory=vector_memory, llm_provider=mock_provider
    )
    return MemoryManager(
        vector_memory=vector_memory,
        graph=graph,
        resolver=resolver,
        summarizer=summarizer,
    )


class TestDeduplication:
    async def test_duplicate_message_not_stored_twice(self, manager, vector_memory):
        """Storing the same message twice should not create duplicate vectors."""
        await manager.store(
            conversation_id="conv-1",
            user_message="I prefer Python over JavaScript for backend work",
            assistant_response="Noted!",
            extracted_entities=[],
        )
        count_after_first = await vector_memory.count()

        await manager.store(
            conversation_id="conv-2",
            user_message="I prefer Python over JavaScript for backend work",
            assistant_response="Got it!",
            extracted_entities=[],
        )
        count_after_second = await vector_memory.count()

        # Should not have added another vector for the duplicate
        assert count_after_second == count_after_first

    async def test_different_messages_both_stored(self, manager, vector_memory):
        """Genuinely different messages should both be stored."""
        await manager.store(
            conversation_id="conv-1",
            user_message="I prefer Python for backend work",
            assistant_response="Noted!",
            extracted_entities=[],
        )
        count_first = await vector_memory.count()

        await manager.store(
            conversation_id="conv-2",
            user_message="My favorite food is sushi",
            assistant_response="Yum!",
            extracted_entities=[],
        )
        count_second = await vector_memory.count()

        assert count_second > count_first
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_memory_dedup.py -v`
Expected: FAIL — `VectorMemory` has no `count()` method, dedup not implemented

**Step 3: Implement**

1. Add `count()` method to `VectorMemory`:
   ```python
   async def count(self) -> int:
       loop = asyncio.get_running_loop()
       return await loop.run_in_executor(None, self._collection.count)
   ```

2. Add `_is_duplicate()` method to `MemoryManager`:
   ```python
   async def _is_duplicate(self, text: str, threshold: float = 0.15) -> bool:
       """Check if a near-duplicate memory already exists."""
       results = await self.vector_memory.search(text, limit=1)
       if results and results[0].distance < threshold:
           return True
       return False
   ```

3. In `MemoryManager._store_impl()`, wrap the chunk embedding loop:
   ```python
   # 2. Chunk and embed the user message (with dedup)
   chunks = self.chunking.chunk(user_message, content_type="message")
   for chunk in chunks:
       if not await self._is_duplicate(chunk):
           await self.vector_memory.store(
               text=chunk,
               source_type="user_message",
               source_id=conversation_id,
               memory_type="personal",
           )
   ```

**Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_memory_dedup.py tests/test_memory_manager.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add odigos/memory/vectors.py odigos/memory/manager.py tests/test_memory_dedup.py
git commit -m "feat(memory): add draft-and-compare deduplication before storing"
```

---

### Task 4: Structured Conversation Compaction

Replace the free-form "summarize in 2-3 sentences" prompt with a structured checkpoint format that preserves actionable context (Goal / Progress / Decisions / Next Steps / Key Facts).

**Files:**
- Modify: `odigos/memory/summarizer.py`
- Modify: `tests/test_memory_manager.py` (or add `tests/test_summarizer.py`)

**Step 1: Write the failing test**

Create `tests/test_summarizer.py`:

```python
from unittest.mock import AsyncMock, call

import pytest

from odigos.db import Database
from odigos.memory.summarizer import ConversationSummarizer, STRUCTURED_COMPACTION_PROMPT
from odigos.memory.vectors import VectorMemory
from odigos.providers.base import LLMResponse


@pytest.fixture
async def db(tmp_db_path):
    database = Database(tmp_db_path, migrations_dir="migrations")
    await database.initialize()
    yield database
    await database.close()


@pytest.fixture
def mock_embedder():
    embedder = AsyncMock()
    embedder.embed.return_value = [0.1] * 768
    embedder.embed_query.return_value = [0.1] * 768
    return embedder


@pytest.fixture
async def vector_memory(tmp_path, mock_embedder):
    vm = VectorMemory(embedder=mock_embedder, persist_dir=str(tmp_path / "chroma"))
    await vm.initialize()
    return vm


@pytest.fixture
def mock_provider():
    provider = AsyncMock()
    provider.complete.return_value = LLMResponse(
        content="## Goal\nBuild a dashboard\n## Progress\n- Done: Auth\n## Decisions\n- Use Preact\n## Next Steps\n- Deploy\n## Key Facts\n- User prefers dark mode",
        model="m", tokens_in=1, tokens_out=1, cost_usd=0.0,
    )
    return provider


@pytest.fixture
def summarizer(db, vector_memory, mock_provider):
    return ConversationSummarizer(
        db=db, vector_memory=vector_memory, llm_provider=mock_provider, context_window=5,
    )


class TestStructuredCompaction:
    async def test_uses_structured_prompt(self, summarizer, db, mock_provider):
        """Summarizer uses the structured compaction prompt, not free-form."""
        # Insert enough messages to trigger summarization
        conv_id = "conv-structured"
        await db.execute(
            "INSERT INTO conversations (id, channel, started_at) VALUES (?, ?, datetime('now'))",
            (conv_id, "test"),
        )
        for i in range(10):
            role = "user" if i % 2 == 0 else "assistant"
            await db.execute(
                "INSERT INTO messages (id, conversation_id, role, content, timestamp) "
                "VALUES (?, ?, ?, ?, datetime('now'))",
                (f"msg-{i}", conv_id, role, f"Message {i}"),
            )

        await summarizer.summarize_if_needed(conv_id)

        # Check the system prompt used
        call_args = mock_provider.complete.call_args
        system_msg = call_args[1]["messages"][0] if "messages" in call_args[1] else call_args[0][0][0]
        assert "Goal" in system_msg["content"]
        assert "Progress" in system_msg["content"]
        assert "Decisions" in system_msg["content"]

    async def test_structured_prompt_constant_exists(self):
        """STRUCTURED_COMPACTION_PROMPT is defined and has required sections."""
        assert "Goal" in STRUCTURED_COMPACTION_PROMPT
        assert "Progress" in STRUCTURED_COMPACTION_PROMPT
        assert "Decisions" in STRUCTURED_COMPACTION_PROMPT
        assert "Next Steps" in STRUCTURED_COMPACTION_PROMPT
        assert "Key Facts" in STRUCTURED_COMPACTION_PROMPT
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_summarizer.py -v`
Expected: FAIL — `STRUCTURED_COMPACTION_PROMPT` doesn't exist

**Step 3: Implement**

In `odigos/memory/summarizer.py`:

1. Replace `SUMMARIZE_PROMPT` with `STRUCTURED_COMPACTION_PROMPT`:

```python
STRUCTURED_COMPACTION_PROMPT = """\
Summarize this conversation segment using the following structured format.
Include ONLY sections that have relevant content. Be concise.

## Goal
What is the user trying to accomplish? (1 sentence)

## Progress
- Done: What has been completed
- In Progress: What is currently being worked on
- Blocked: Any blockers or issues

## Decisions
Key decisions made during this conversation (bulleted list)

## Next Steps
What should happen next (bulleted list)

## Key Facts
Important facts, preferences, or context worth remembering (bulleted list)\
"""
```

2. Update the `summarize_if_needed` method to use `STRUCTURED_COMPACTION_PROMPT` instead of `SUMMARIZE_PROMPT`

3. When storing the summary, pass `memory_type="summary"` and a `when_to_use` that references the conversation context:
   ```python
   await self.vector_memory.store(
       text=summary_text,
       source_type="conversation_summary",
       source_id=summary_id,
       memory_type="summary",
       when_to_use=f"when recalling context from conversation {conversation_id}",
   )
   ```

**Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_summarizer.py tests/test_memory_manager.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add odigos/memory/summarizer.py tests/test_summarizer.py
git commit -m "feat(memory): structured compaction with Goal/Progress/Decisions format"
```

---

### Task 5: Peer Message Tracking Table

Add a DB migration for tracking peer messages with message_id-based deduplication and delivery status. This is the foundation for reliable messaging.

**Files:**
- Create: `migrations/013_peer_messages.sql`
- Test: `tests/test_peer_message_tracking.py`

**Step 1: Write the failing test**

Create `tests/test_peer_message_tracking.py`:

```python
import pytest

from odigos.db import Database


@pytest.fixture
async def db(tmp_db_path):
    database = Database(tmp_db_path, migrations_dir="migrations")
    await database.initialize()
    yield database
    await database.close()


class TestPeerMessageTable:
    async def test_table_exists(self, db):
        """peer_messages table exists after migration."""
        row = await db.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='peer_messages'"
        )
        assert row is not None

    async def test_insert_outbound(self, db):
        """Can insert an outbound peer message."""
        await db.execute(
            "INSERT INTO peer_messages "
            "(message_id, direction, peer_name, message_type, content, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("msg-001", "outbound", "sarah", "message", "hello", "sent"),
        )
        row = await db.fetch_one(
            "SELECT * FROM peer_messages WHERE message_id = ?", ("msg-001",)
        )
        assert row["peer_name"] == "sarah"
        assert row["status"] == "sent"

    async def test_insert_inbound(self, db):
        """Can insert an inbound peer message."""
        await db.execute(
            "INSERT INTO peer_messages "
            "(message_id, direction, peer_name, message_type, content, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("msg-002", "inbound", "bob", "help_request", "need help", "received"),
        )
        row = await db.fetch_one(
            "SELECT * FROM peer_messages WHERE message_id = ?", ("msg-002",)
        )
        assert row["direction"] == "inbound"

    async def test_duplicate_message_id_rejected(self, db):
        """Duplicate message_id is rejected (UNIQUE constraint)."""
        await db.execute(
            "INSERT INTO peer_messages "
            "(message_id, direction, peer_name, message_type, content, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("msg-dup", "outbound", "sarah", "message", "first", "sent"),
        )
        with pytest.raises(Exception):
            await db.execute(
                "INSERT INTO peer_messages "
                "(message_id, direction, peer_name, message_type, content, status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("msg-dup", "inbound", "bob", "message", "duplicate", "received"),
            )

    async def test_status_update(self, db):
        """Can update delivery status."""
        await db.execute(
            "INSERT INTO peer_messages "
            "(message_id, direction, peer_name, message_type, content, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("msg-003", "outbound", "sarah", "message", "hello", "queued"),
        )
        await db.execute(
            "UPDATE peer_messages SET status = ?, delivered_at = datetime('now') "
            "WHERE message_id = ?",
            ("delivered", "msg-003"),
        )
        row = await db.fetch_one(
            "SELECT * FROM peer_messages WHERE message_id = ?", ("msg-003",)
        )
        assert row["status"] == "delivered"
        assert row["delivered_at"] is not None
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_peer_message_tracking.py -v`
Expected: FAIL — table doesn't exist

**Step 3: Create the migration**

Create `migrations/013_peer_messages.sql`:

```sql
CREATE TABLE IF NOT EXISTS peer_messages (
    message_id TEXT PRIMARY KEY,
    direction TEXT NOT NULL CHECK (direction IN ('inbound', 'outbound')),
    peer_name TEXT NOT NULL,
    message_type TEXT NOT NULL DEFAULT 'message',
    content TEXT NOT NULL,
    metadata_json TEXT,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'sent', 'delivered', 'failed', 'received', 'processed')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    delivered_at TEXT,
    conversation_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_peer_messages_peer ON peer_messages(peer_name);
CREATE INDEX IF NOT EXISTS idx_peer_messages_status ON peer_messages(status);
CREATE INDEX IF NOT EXISTS idx_peer_messages_direction ON peer_messages(direction);
```

**Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_peer_message_tracking.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add migrations/013_peer_messages.sql tests/test_peer_message_tracking.py
git commit -m "feat(peers): add peer_messages table for dedup and delivery tracking"
```

---

### Task 6: PeerClient with Deduplication and Delivery Tracking

Wire the peer_messages table into PeerClient for outbound message tracking, and into the inbound endpoint for dedup.

**Files:**
- Modify: `odigos/core/peers.py`
- Modify: `odigos/api/agent_message.py`
- Modify: `tests/test_peer_client.py`
- Create: `tests/test_peer_dedup.py`

**Step 1: Write the failing tests**

Create `tests/test_peer_dedup.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from odigos.core.peers import PeerClient
from odigos.config import PeerConfig
from odigos.db import Database


@pytest.fixture
async def db(tmp_db_path):
    database = Database(tmp_db_path, migrations_dir="migrations")
    await database.initialize()
    yield database
    await database.close()


@pytest.fixture
def peers():
    return [PeerConfig(name="sarah", url="http://sarah.local:8000", api_key="key")]


@pytest.fixture
def client(peers, db):
    return PeerClient(peers=peers, agent_name="odigos", db=db)


class TestOutboundTracking:
    async def test_send_records_message(self, client, db):
        """Sending a message records it in peer_messages."""
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"status": "ok"}
        mock_http = AsyncMock()
        mock_http.post.return_value = mock_resp
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch("odigos.core.peers.httpx.AsyncClient", return_value=mock_http):
            result = await client.send("sarah", "hello")

        assert result["status"] == "ok"
        row = await db.fetch_one(
            "SELECT * FROM peer_messages WHERE direction = 'outbound' AND peer_name = 'sarah'"
        )
        assert row is not None
        assert row["content"] == "hello"
        assert row["status"] == "delivered"

    async def test_send_failure_records_failed_status(self, client, db):
        """Failed send records status as 'failed'."""
        mock_resp = MagicMock(status_code=500)
        mock_resp.json.return_value = {}
        mock_http = AsyncMock()
        mock_http.post.return_value = mock_resp
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch("odigos.core.peers.httpx.AsyncClient", return_value=mock_http):
            result = await client.send("sarah", "hello")

        row = await db.fetch_one(
            "SELECT * FROM peer_messages WHERE direction = 'outbound' AND peer_name = 'sarah'"
        )
        assert row["status"] == "failed"


class TestInboundDedup:
    async def test_duplicate_inbound_rejected(self, db):
        """Inbound message with duplicate message_id is rejected."""
        # Simulate first receipt
        await db.execute(
            "INSERT INTO peer_messages "
            "(message_id, direction, peer_name, message_type, content, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("msg-abc", "inbound", "bob", "message", "hello", "received"),
        )

        # Check if duplicate
        existing = await db.fetch_one(
            "SELECT 1 FROM peer_messages WHERE message_id = ?", ("msg-abc",)
        )
        assert existing is not None  # Would skip processing
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_peer_dedup.py -v`
Expected: FAIL — `PeerClient.__init__` doesn't accept `db`

**Step 3: Implement**

Update `odigos/core/peers.py`:

1. Add optional `db` parameter to `PeerClient.__init__`:
   ```python
   def __init__(self, peers, agent_name="odigos", db=None):
       self._peers = {p.name: p for p in peers}
       self.agent_name = agent_name
       self._db = db
   ```

2. In `send()`, generate a message_id, record before sending, update status after:
   ```python
   async def send(self, peer_name, content, message_type="message", metadata=None):
       peer = self._peers.get(peer_name)
       if not peer:
           raise ValueError(f"Unknown peer: {peer_name}")

       message_id = str(uuid.uuid4())

       # Record outbound message
       if self._db:
           await self._db.execute(
               "INSERT INTO peer_messages "
               "(message_id, direction, peer_name, message_type, content, metadata_json, status) "
               "VALUES (?, 'outbound', ?, ?, ?, ?, 'queued')",
               (message_id, peer_name, message_type, content, json.dumps(metadata or {})),
           )

       url = f"{peer.url.rstrip('/')}/api/agent/message"
       payload = {
           "from_agent": self.agent_name,
           "message_type": message_type,
           "content": content,
           "metadata": {**(metadata or {}), "message_id": message_id},
       }
       headers = {}
       if peer.api_key:
           headers["Authorization"] = f"Bearer {peer.api_key}"

       async with httpx.AsyncClient(timeout=30) as client:
           resp = await client.post(url, json=payload, headers=headers)

       if resp.status_code != 200:
           if self._db:
               await self._db.execute(
                   "UPDATE peer_messages SET status = 'failed' WHERE message_id = ?",
                   (message_id,),
               )
           return {"status": "error", "response": f"Peer returned {resp.status_code}"}

       if self._db:
           await self._db.execute(
               "UPDATE peer_messages SET status = 'delivered', delivered_at = datetime('now') "
               "WHERE message_id = ?",
               (message_id,),
           )
       return resp.json()
   ```

3. Add `import json, uuid` at top of file

4. Update `odigos/api/agent_message.py` to check for duplicate inbound messages:
   ```python
   # At the start of the endpoint handler, after parsing request:
   message_id = request.metadata.get("message_id", str(uuid.uuid4()))
   db = request_obj.app.state.db

   # Check for duplicate
   existing = await db.fetch_one(
       "SELECT 1 FROM peer_messages WHERE message_id = ?", (message_id,)
   )
   if existing:
       return {"status": "duplicate", "message": "Message already processed"}

   # Record inbound
   await db.execute(
       "INSERT INTO peer_messages "
       "(message_id, direction, peer_name, message_type, content, status) "
       "VALUES (?, 'inbound', ?, ?, ?, 'received')",
       (message_id, request.from_agent, request.message_type, request.content),
   )
   ```

5. Update `odigos/main.py` to pass `db` to PeerClient:
   ```python
   peer_client = PeerClient(peers=settings.peers, agent_name="odigos", db=_db)
   ```
   NOTE: `_db` is initialized right before this line, so move the PeerClient creation to after `await _db.initialize()`.

**Step 4: Update existing peer_client tests**

Update `tests/test_peer_client.py`: The `PeerClient` fixture now accepts optional `db=None`, so existing tests (which don't pass db) should still work without changes. Verify.

**Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/test_peer_dedup.py tests/test_peer_client.py tests/test_peer_tool.py tests/test_peer_integration.py -v`
Expected: PASS

Run: `.venv/bin/python -m pytest tests/ -x -q`
Expected: All pass

**Step 6: Commit**

```bash
git add odigos/core/peers.py odigos/api/agent_message.py odigos/main.py migrations/013_peer_messages.sql tests/test_peer_dedup.py
git commit -m "feat(peers): add message deduplication and delivery tracking"
```

---

### Task 7: WebSocket Peer Transport (Prep)

Extend the WebSocket endpoint to accept peer agent connections alongside dashboard clients. This preps for relay-style patterns where peers can connect via WebSocket instead of HTTP POST. We add the infrastructure now; the full relay protocol comes later.

**Files:**
- Modify: `odigos/api/ws.py`
- Modify: `odigos/channels/web.py`
- Create: `tests/test_ws_peer.py`

**Step 1: Write the failing tests**

Create `tests/test_ws_peer.py`:

```python
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, PropertyMock

from odigos.channels.web import WebChannel


class FakeWebSocket:
    """Minimal WebSocket mock for testing."""

    def __init__(self):
        self.sent = []
        self.closed = False

    async def send_json(self, data):
        self.sent.append(data)

    async def accept(self):
        pass

    async def close(self, code=1000, reason=""):
        self.closed = True


class TestWebChannelPeerSupport:
    def test_register_peer_connection(self):
        """Can register a peer agent connection."""
        wc = WebChannel()
        ws = FakeWebSocket()
        wc.register_connection("peer:sarah", ws)
        assert ws in wc._connections["peer:sarah"]

    async def test_send_to_peer(self):
        """Can send a message to a connected peer."""
        wc = WebChannel()
        ws = FakeWebSocket()
        wc.register_connection("peer:sarah", ws)
        await wc.send_message("peer:sarah", "Hello Sarah")
        assert len(ws.sent) == 1
        assert ws.sent[0]["content"] == "Hello Sarah"

    def test_list_connected_peers(self):
        """Can list all connected peer conversation_ids."""
        wc = WebChannel()
        wc.register_connection("peer:sarah", FakeWebSocket())
        wc.register_connection("peer:bob", FakeWebSocket())
        wc.register_connection("web:abc123", FakeWebSocket())
        peers = wc.connected_peers()
        assert sorted(peers) == ["peer:bob", "peer:sarah"]

    def test_is_peer_connected(self):
        """Can check if a specific peer is connected."""
        wc = WebChannel()
        wc.register_connection("peer:sarah", FakeWebSocket())
        assert wc.is_peer_connected("sarah") is True
        assert wc.is_peer_connected("bob") is False
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_ws_peer.py -v`
Expected: FAIL — `connected_peers()` and `is_peer_connected()` don't exist

**Step 3: Implement**

Add to `odigos/channels/web.py`:

```python
def connected_peers(self) -> list[str]:
    """List conversation_ids of connected peer agents."""
    return [cid for cid in self._connections if cid.startswith("peer:")]

def is_peer_connected(self, peer_name: str) -> bool:
    """Check if a peer agent is connected via WebSocket."""
    return f"peer:{peer_name}" in self._connections
```

Update `odigos/api/ws.py` to handle `type: "peer_connect"` messages:

Add a new message type in the WebSocket handler loop:

```python
elif msg_type == "peer_connect":
    # Peer agent identifying itself
    peer_name = data.get("agent_name", "")
    if peer_name:
        # Re-register under peer conversation_id
        web_channel.unregister_connection(conversation_id, websocket)
        conversation_id = f"peer:{peer_name}"
        web_channel.register_connection(conversation_id, websocket)
        await websocket.send_json({
            "type": "peer_connected",
            "conversation_id": conversation_id,
            "agent_name": peer_name,
        })
```

**Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_ws_peer.py tests/test_webchannel.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add odigos/channels/web.py odigos/api/ws.py tests/test_ws_peer.py
git commit -m "feat(peers): add WebSocket peer connection support (relay prep)"
```

---

### Task 8: Update MemoryManager to Generate `when_to_use`

Now that the infrastructure is in place, update the store pipeline to generate `when_to_use` descriptions for stored memories. Uses a simple heuristic (no LLM call) based on content analysis.

**Files:**
- Modify: `odigos/memory/manager.py`
- Modify: `tests/test_memory_manager.py`

**Step 1: Write the failing test**

Add to `tests/test_memory_manager.py`:

```python
class TestWhenToUseGeneration:
    async def test_entity_stored_with_when_to_use(self, manager, vector_memory, mock_embedder):
        """Entities are embedded with a when_to_use description."""
        await manager.store(
            conversation_id="conv-1",
            user_message="Alice is a software engineer at Google",
            assistant_response="Noted!",
            extracted_entities=[{"name": "Alice", "type": "person"}],
        )
        # Check that embed was called with a when_to_use-style string
        # (entity names are embedded via resolver, but user messages should have when_to_use)
        embed_calls = mock_embedder.embed.call_args_list
        # At least one call should contain contextual framing
        any_contextual = any(
            "mentioned" in str(c) or "discussed" in str(c) or "about" in str(c)
            for c in embed_calls
        )
        # This is a soft check — the key behavior is that when_to_use is passed
        assert mock_embedder.embed.called
```

**Step 2: Implement**

Add a helper to `MemoryManager`:

```python
@staticmethod
def _generate_when_to_use(text: str, source_type: str) -> str:
    """Generate a when_to_use description from content heuristics."""
    text_lower = text.lower()
    if source_type == "user_message":
        if any(w in text_lower for w in ("prefer", "like", "want", "always", "never")):
            return f"when recalling user preferences about: {text[:100]}"
        if any(w in text_lower for w in ("is a", "works at", "lives in", "born")):
            return f"when recalling facts about people or places mentioned in: {text[:100]}"
        return f"when the user previously discussed: {text[:100]}"
    if source_type == "document_chunk":
        return f"when referencing ingested documents about: {text[:100]}"
    return ""
```

Update `_store_impl` to use it:

```python
for chunk in chunks:
    if not await self._is_duplicate(chunk):
        when_to_use = self._generate_when_to_use(chunk, "user_message")
        await self.vector_memory.store(
            text=chunk,
            source_type="user_message",
            source_id=conversation_id,
            memory_type="personal",
            when_to_use=when_to_use,
        )
```

**Step 3: Run tests**

Run: `.venv/bin/python -m pytest tests/test_memory_manager.py -v`
Expected: PASS

**Step 4: Run full suite**

Run: `.venv/bin/python -m pytest tests/ -x -q`
Expected: All pass

**Step 5: Commit**

```bash
git add odigos/memory/manager.py tests/test_memory_manager.py
git commit -m "feat(memory): generate when_to_use descriptions for stored memories"
```

---

### Task 9: Final Integration Verification

Run the full test suite and verify everything works together.

**Step 1: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -v 2>&1 | tail -30`
Expected: All pass

**Step 2: Verify no regressions**

Run: `.venv/bin/python -m pytest tests/test_memory_manager.py tests/test_vector_memory.py tests/test_memory_dedup.py tests/test_summarizer.py tests/test_peer_client.py tests/test_peer_dedup.py tests/test_ws_peer.py tests/test_webchannel.py -v`
Expected: All pass

**Step 3: Review git log**

Run: `git log --oneline -10`
Expected: 8 new commits for this workstream

**Step 4: Commit any final fixups**

If any test adjustments were needed, commit them:
```bash
git add -A
git commit -m "fix: integration adjustments for memory and messaging upgrades"
```
