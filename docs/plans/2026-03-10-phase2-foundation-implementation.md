# Phase 2 Foundation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the foundation layer for Phase 2 — error recovery, unified chunking, ChromaDB vector storage, MarkItDown document processing, and the plugin architecture.

**Architecture:** Four parallel workstreams that share no dependencies: (1) harden the core request path against failures, (2) replace naive chunking + sqlite-vec with Chonkie + ChromaDB, (3) add MarkItDown as default document processor and move Docling to a plugin, (4) build the plugin loader with extension points for tools, channels, and providers. Each workstream produces independently testable changes.

**Tech Stack:** Python 3.12, pytest, aiosqlite, ChromaDB (embedded), Chonkie, MarkItDown, FastAPI

**Reference:** Design doc at `docs/plans/2026-03-10-phase2-shippable-agent-design.md`

---

## Workstream 1: Error Recovery Hardening

### Task 1: Executor LLM call error handling

**Files:**
- Modify: `odigos/core/executor.py:131-132`
- Modify: `odigos/core/agent.py:122-129`
- Test: `tests/test_core.py`

**Step 1: Write the failing test**

In `tests/test_core.py`, add to the existing test class:

```python
class TestExecutorErrorRecovery:
    async def test_llm_failure_returns_graceful_message(self, db: Database):
        """Executor returns a user-friendly message when all LLM models fail."""
        from unittest.mock import AsyncMock
        from odigos.core.executor import Executor

        provider = AsyncMock()
        provider.complete.side_effect = RuntimeError("All LLM providers failed")

        context = AsyncMock()
        context.build.return_value = [
            {"role": "system", "content": "test"},
            {"role": "user", "content": "hello"},
        ]

        executor = Executor(provider=provider, context_assembler=context, db=db)
        result = await executor.execute("test-conv", "hello")

        assert result.response.content is not None
        assert "trouble" in result.response.content.lower() or "couldn't" in result.response.content.lower()
        assert result.response.model == "system"

    async def test_llm_failure_does_not_crash(self, db: Database):
        """Agent.handle_message doesn't propagate LLM exceptions to the caller."""
        from unittest.mock import AsyncMock
        from odigos.channels.base import UniversalMessage
        from odigos.core.agent import Agent

        provider = AsyncMock()
        provider.complete.side_effect = RuntimeError("Connection refused")

        agent = Agent(db=db, provider=provider)
        msg = UniversalMessage(
            id="test-1", content="hello", sender="user1",
            channel="test", metadata={"chat_id": "1"},
        )
        # Should NOT raise
        response = await agent.handle_message(msg)
        assert isinstance(response, str)
        assert len(response) > 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_core.py::TestExecutorErrorRecovery -v`
Expected: FAIL — RuntimeError propagates uncaught

**Step 3: Implement error handling**

In `odigos/core/executor.py`, wrap the LLM call at line 132:

```python
            # Call LLM
            try:
                response = await self.provider.complete(messages, tools=tools)
            except Exception as e:
                logger.error("LLM call failed at turn %d: %s", turn, e)
                if last_response is not None:
                    # We have a partial result from earlier turns, return it
                    break
                # No response at all — return a graceful system message
                last_response = LLMResponse(
                    content="I'm having trouble reaching my language model right now. Please try again in a moment.",
                    model="system",
                    tokens_in=0,
                    tokens_out=0,
                    cost_usd=0.0,
                )
                break
```

In `odigos/core/agent.py`, add a catch around the executor call at line 122-129:

```python
        try:
            async with asyncio.timeout(self._run_timeout):
                result = await self.executor.execute(conversation_id, message.content)
        except asyncio.TimeoutError:
            logger.warning("Run timed out after %ds for %s", self._run_timeout, conversation_id)
            if self.tracer:
                await self.tracer.emit("timeout", conversation_id, {"timeout_seconds": self._run_timeout})
            return "I ran out of time working on that. Try breaking it into smaller pieces."
        except Exception as e:
            logger.exception("Agent run failed for %s", conversation_id)
            if self.tracer:
                await self.tracer.emit("error", conversation_id, {"error": str(e)[:500]})
            return "Something went wrong while processing your message. Please try again."
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_core.py::TestExecutorErrorRecovery -v`
Expected: PASS

**Step 5: Commit**

```bash
git add odigos/core/executor.py odigos/core/agent.py tests/test_core.py
git commit -m "fix: graceful error handling for LLM call failures in executor and agent"
```

---

### Task 2: Embedding failure resilience

**Files:**
- Modify: `odigos/memory/manager.py:66-104`
- Modify: `odigos/core/reflector.py:111-118`
- Test: `tests/test_core.py`

**Step 1: Write the failing test**

```python
class TestEmbeddingFailureResilience:
    async def test_memory_store_survives_embedding_failure(self, db: Database):
        """MemoryManager.store() logs warning but doesn't raise when embedding fails."""
        from unittest.mock import AsyncMock
        from odigos.memory.manager import MemoryManager

        vector_memory = AsyncMock()
        vector_memory.store.side_effect = RuntimeError("Embedding model crashed")
        graph = AsyncMock()
        resolver = AsyncMock()
        resolver.resolve.return_value = AsyncMock(entity_id="e1")
        summarizer = AsyncMock()

        mm = MemoryManager(
            vector_memory=vector_memory, graph=graph,
            resolver=resolver, summarizer=summarizer,
        )

        # Should NOT raise
        await mm.store(
            conversation_id="c1",
            user_message="hello",
            assistant_response="hi",
            extracted_entities=[],
        )

    async def test_reflector_survives_memory_failure(self, db: Database):
        """Reflector.reflect() returns clean content even if memory storage fails."""
        from unittest.mock import AsyncMock
        from odigos.core.reflector import Reflector
        from odigos.providers.base import LLMResponse

        memory_manager = AsyncMock()
        memory_manager.store.side_effect = RuntimeError("Memory system down")

        reflector = Reflector(db=db, memory_manager=memory_manager)
        response = LLMResponse(
            content="Hello there!", model="test",
            tokens_in=10, tokens_out=5, cost_usd=0.001,
        )

        # Should NOT raise, should return clean content
        result = await reflector.reflect("c1", response, user_message="hi")
        assert result == "Hello there!"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_core.py::TestEmbeddingFailureResilience -v`
Expected: FAIL — RuntimeError propagates

**Step 3: Implement resilience**

In `odigos/memory/manager.py`, wrap the store method body:

```python
    async def store(
        self,
        conversation_id: str,
        user_message: str,
        assistant_response: str,
        extracted_entities: list[dict],
    ) -> None:
        """Process and store memories from a conversation turn.

        Best-effort: failures are logged but don't crash the agent.
        """
        try:
            await self._store_impl(conversation_id, user_message, assistant_response, extracted_entities)
        except Exception:
            logger.warning("Memory storage failed, skipping this turn", exc_info=True)

    async def _store_impl(
        self,
        conversation_id: str,
        user_message: str,
        assistant_response: str,
        extracted_entities: list[dict],
    ) -> None:
        # (move existing store body here unchanged)
```

In `odigos/core/reflector.py`, wrap the memory_manager.store call at lines 111-118:

```python
        # Pass to memory manager if available (best-effort)
        if self.memory_manager and user_message is not None:
            try:
                await self.memory_manager.store(
                    conversation_id=conversation_id,
                    user_message=user_message,
                    assistant_response=content,
                    extracted_entities=entities,
                )
            except Exception:
                logger.warning("Memory storage failed during reflection", exc_info=True)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_core.py::TestEmbeddingFailureResilience -v`
Expected: PASS

**Step 5: Commit**

```bash
git add odigos/memory/manager.py odigos/core/reflector.py tests/test_core.py
git commit -m "fix: memory and embedding failures degrade gracefully instead of crashing"
```

---

### Task 3: Database retry for SQLITE_BUSY

**Files:**
- Modify: `odigos/db.py:70-104`
- Test: `tests/test_db.py`

**Step 1: Write the failing test**

```python
import aiosqlite

class TestDatabaseRetry:
    async def test_execute_retries_on_busy(self, tmp_path):
        """Database.execute() retries on SQLITE_BUSY and succeeds."""
        from unittest.mock import AsyncMock, patch
        from odigos.db import Database

        db = Database(str(tmp_path / "test.db"), migrations_dir=str(tmp_path / "m"))
        await db.initialize()

        call_count = 0
        original_execute = db.conn.execute

        async def flaky_execute(sql, params=()):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise aiosqlite.OperationalError("database is locked")
            return await original_execute(sql, params)

        with patch.object(db.conn, "execute", side_effect=flaky_execute):
            # Patch commit too since it follows execute
            with patch.object(db.conn, "commit", new_callable=AsyncMock):
                await db.execute("SELECT 1")

        assert call_count == 2  # First try failed, second succeeded
        await db.close()

    async def test_execute_raises_after_max_retries(self, tmp_path):
        """Database.execute() raises after exhausting retries."""
        from unittest.mock import patch
        from odigos.db import Database

        db = Database(str(tmp_path / "test.db"), migrations_dir=str(tmp_path / "m"))
        await db.initialize()

        async def always_locked(sql, params=()):
            raise aiosqlite.OperationalError("database is locked")

        with patch.object(db.conn, "execute", side_effect=always_locked):
            with pytest.raises(aiosqlite.OperationalError):
                await db.execute("SELECT 1")

        await db.close()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_db.py::TestDatabaseRetry -v`
Expected: FAIL — no retry logic exists

**Step 3: Implement retry logic**

In `odigos/db.py`, add retry helper and update `execute`, `fetch_one`, `fetch_all`, `execute_returning_lastrowid`:

```python
import asyncio
import logging

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_DELAYS = (0.1, 0.2, 0.4)  # seconds


async def _retry_on_busy(coro_factory, max_retries=_MAX_RETRIES):
    """Retry a coroutine factory on SQLITE_BUSY with exponential backoff."""
    for attempt in range(max_retries + 1):
        try:
            return await coro_factory()
        except aiosqlite.OperationalError as e:
            if "locked" not in str(e).lower() and "busy" not in str(e).lower():
                raise
            if attempt >= max_retries:
                raise
            delay = _RETRY_DELAYS[attempt] if attempt < len(_RETRY_DELAYS) else _RETRY_DELAYS[-1]
            logger.warning("DB busy, retrying in %.1fs (attempt %d/%d)", delay, attempt + 1, max_retries)
            await asyncio.sleep(delay)
```

Then update each method to use it:

```python
    async def execute(self, sql: str, params: tuple = ()) -> None:
        async def _do():
            await self.conn.execute(sql, params)
            await self.conn.commit()
        await _retry_on_busy(_do)

    async def execute_returning_lastrowid(self, sql: str, params: tuple = ()) -> int:
        result = None
        async def _do():
            nonlocal result
            cursor = await self.conn.execute(sql, params)
            await self.conn.commit()
            result = cursor.lastrowid
        await _retry_on_busy(_do)
        return result

    async def fetch_one(self, sql: str, params: tuple = ()) -> dict | None:
        result = None
        async def _do():
            nonlocal result
            cursor = await self.conn.execute(sql, params)
            row = await cursor.fetchone()
            result = dict(row) if row else None
        await _retry_on_busy(_do)
        return result

    async def fetch_all(self, sql: str, params: tuple = ()) -> list[dict]:
        result = []
        async def _do():
            nonlocal result
            cursor = await self.conn.execute(sql, params)
            rows = await cursor.fetchall()
            result = [dict(row) for row in rows]
        await _retry_on_busy(_do)
        return result
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_db.py::TestDatabaseRetry -v`
Expected: PASS

**Step 5: Commit**

```bash
git add odigos/db.py tests/test_db.py
git commit -m "fix: add retry with backoff for SQLITE_BUSY in Database operations"
```

---

### Task 4: Transaction safety for reflector and ingester

**Files:**
- Modify: `odigos/core/reflector.py:90-129`
- Modify: `odigos/memory/ingester.py:59-64`
- Test: `tests/test_core.py`

**Step 1: Write the failing test**

```python
class TestTransactionSafety:
    async def test_reflector_stores_message_even_if_scrape_logging_fails(self, db: Database):
        """Reflector saves the assistant message even if scrape metadata insertion fails."""
        from unittest.mock import AsyncMock, patch
        from odigos.core.reflector import Reflector
        from odigos.providers.base import LLMResponse

        reflector = Reflector(db=db)
        response = LLMResponse(
            content="Here is the info", model="test",
            tokens_in=10, tokens_out=5, cost_usd=0.001,
        )

        # Make scrape insertion fail
        scrape_meta = {"url": "https://example.com", "title": "Test", "content": "x"}
        original_execute = db.execute

        call_count = 0
        async def failing_scrape_execute(sql, params=()):
            nonlocal call_count
            call_count += 1
            if "scraped_pages" in sql:
                raise RuntimeError("DB error on scrape insert")
            return await original_execute(sql, params)

        with patch.object(db, "execute", side_effect=failing_scrape_execute):
            result = await reflector.reflect("c1", response, scrape_metadata=scrape_meta)

        assert result == "Here is the info"
        # Message should still be stored
        msgs = await db.fetch_all("SELECT * FROM messages WHERE conversation_id = 'c1'")
        assert len(msgs) == 1

    async def test_ingester_records_partial_chunk_count(self, db: Database):
        """DocumentIngester records chunks that were successfully stored before failure."""
        from unittest.mock import AsyncMock
        from odigos.memory.ingester import DocumentIngester

        vector_memory = AsyncMock()
        store_count = 0
        async def store_then_fail(**kwargs):
            nonlocal store_count
            store_count += 1
            if store_count >= 3:
                raise RuntimeError("Embedding failed")
            return "vec-id"
        vector_memory.store.side_effect = store_then_fail

        ingester = DocumentIngester(db=db, vector_memory=vector_memory)
        text = "Para one.\n\nPara two.\n\nPara three.\n\nPara four."

        # Should not raise, should record partial progress
        doc_id = await ingester.ingest(text, "test.txt")

        doc = await db.fetch_one("SELECT * FROM documents WHERE id = ?", (doc_id,))
        assert doc is not None
        # chunk_count should reflect what was actually stored (2 of 4)
        assert doc["chunk_count"] == 2
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_core.py::TestTransactionSafety -v`
Expected: FAIL

**Step 3: Implement transaction safety**

In `odigos/core/reflector.py`, wrap scrape logging in try/catch:

```python
        # Log scrape if metadata provided (best-effort)
        if scrape_metadata:
            try:
                url = scrape_metadata.get("url", "")
                title = scrape_metadata.get("title", "")
                content_text = scrape_metadata.get("content", "")
                summary = content_text[:200] if content_text else ""
                await self.db.execute(
                    "INSERT INTO scraped_pages (id, url, title, summary) VALUES (?, ?, ?, ?)",
                    (str(uuid.uuid4()), url, title, summary),
                )
            except Exception:
                logger.warning("Failed to log scrape metadata", exc_info=True)
```

In `odigos/memory/ingester.py`, track successful chunks and update count on failure:

```python
        stored_count = 0
        for chunk_text in chunks:
            try:
                await self.vector_memory.store(
                    text=chunk_text,
                    source_type="document_chunk",
                    source_id=doc_id,
                )
                stored_count += 1
            except Exception:
                logger.warning(
                    "Failed to store chunk %d/%d for document %s",
                    stored_count + 1, len(chunks), doc_id, exc_info=True,
                )
                break

        # Update with actual stored chunk count
        await self.db.execute(
            "UPDATE documents SET chunk_count = ? WHERE id = ?",
            (stored_count, doc_id),
        )
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_core.py::TestTransactionSafety -v`
Expected: PASS

**Step 5: Commit**

```bash
git add odigos/core/reflector.py odigos/memory/ingester.py tests/test_core.py
git commit -m "fix: transaction safety for reflector scrape logging and document ingestion"
```

---

## Workstream 2: Chunking + ChromaDB

### Task 5: Add Chonkie dependency and ChunkingService

**Files:**
- Modify: `pyproject.toml`
- Create: `odigos/memory/chunking.py`
- Test: `tests/test_chunking.py`

**Step 1: Add dependency**

In `pyproject.toml`, add to dependencies:

```toml
"chonkie[semantic]>=1.0.0",
```

Run: `pip install -e ".[dev]"` to install.

**Step 2: Write the failing test**

Create `tests/test_chunking.py`:

```python
import pytest
from odigos.memory.chunking import ChunkingService


class TestChunkingService:
    def test_short_text_not_chunked(self):
        """Short text (<500 tokens) is returned as-is."""
        cs = ChunkingService()
        result = cs.chunk("Hello world, this is a short message.", content_type="message")
        assert result == ["Hello world, this is a short message."]

    def test_long_text_is_chunked(self):
        """Long text is split into multiple chunks."""
        cs = ChunkingService()
        long_text = "This is a sentence about dogs. " * 200
        result = cs.chunk(long_text, content_type="message")
        assert len(result) > 1
        # All original content should be present across chunks
        combined = " ".join(result)
        assert "dogs" in combined

    def test_document_chunking(self):
        """Document content type uses recursive chunking."""
        cs = ChunkingService()
        doc = "# Title\n\nFirst paragraph about topic A.\n\n## Section 2\n\nSecond paragraph about topic B.\n\n" * 20
        result = cs.chunk(doc, content_type="document")
        assert len(result) > 1

    def test_code_chunking(self):
        """Code content type respects structural boundaries."""
        cs = ChunkingService()
        code = '''
def foo():
    return 1

def bar():
    return 2

class Baz:
    def method(self):
        return 3
''' * 20
        result = cs.chunk(code, content_type="code")
        assert len(result) > 1

    def test_empty_text_returns_empty(self):
        """Empty string returns empty list."""
        cs = ChunkingService()
        assert cs.chunk("", content_type="message") == []

    def test_whitespace_only_returns_empty(self):
        """Whitespace-only text returns empty list."""
        cs = ChunkingService()
        assert cs.chunk("   \n\n  ", content_type="message") == []
```

**Step 3: Run test to verify it fails**

Run: `pytest tests/test_chunking.py -v`
Expected: FAIL — module doesn't exist

**Step 4: Implement ChunkingService**

Create `odigos/memory/chunking.py`:

```python
from __future__ import annotations

import logging

import tiktoken

logger = logging.getLogger(__name__)

_tokenizer = tiktoken.get_encoding("cl100k_base")
SHORT_TEXT_THRESHOLD = 500  # tokens


class ChunkingService:
    """Unified chunking layer using Chonkie.

    Routes text to the appropriate chunker based on content_type:
    - "message": SemanticChunker for long messages, as-is for short ones
    - "document": RecursiveChunker for structured documents
    - "code": CodeChunker for source code
    - "text": SentenceChunker for plain text (e.g. MarkItDown output)
    """

    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 64) -> None:
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._chunkers: dict = {}

    def _get_chunker(self, content_type: str):
        """Lazy-load chunkers to avoid import cost at startup."""
        if content_type not in self._chunkers:
            if content_type == "message":
                from chonkie import SemanticChunker
                self._chunkers[content_type] = SemanticChunker(
                    chunk_size=self._chunk_size,
                    chunk_overlap=self._chunk_overlap,
                )
            elif content_type == "document":
                from chonkie import RecursiveChunker
                self._chunkers[content_type] = RecursiveChunker(
                    chunk_size=self._chunk_size,
                    chunk_overlap=self._chunk_overlap,
                )
            elif content_type == "code":
                from chonkie import CodeChunker
                self._chunkers[content_type] = CodeChunker(
                    chunk_size=self._chunk_size,
                    chunk_overlap=self._chunk_overlap,
                )
            else:  # "text" or fallback
                from chonkie import SentenceChunker
                self._chunkers[content_type] = SentenceChunker(
                    chunk_size=self._chunk_size,
                    chunk_overlap=self._chunk_overlap,
                )
        return self._chunkers[content_type]

    def chunk(self, text: str, content_type: str = "message") -> list[str]:
        """Split text into chunks appropriate for the content type.

        Returns the text as-is (single-element list) if it's short enough.
        Returns empty list for empty/whitespace-only text.
        """
        if not text or not text.strip():
            return []

        text = text.strip()

        # Short text doesn't need chunking
        token_count = len(_tokenizer.encode(text, disallowed_special=()))
        if token_count <= SHORT_TEXT_THRESHOLD:
            return [text]

        try:
            chunker = self._get_chunker(content_type)
            chunks = chunker.chunk(text)
            return [c.text for c in chunks if c.text.strip()]
        except Exception:
            logger.warning("Chunking failed, falling back to paragraph split", exc_info=True)
            paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
            return paragraphs if paragraphs else [text]
```

**Step 5: Run tests to verify they pass**

Run: `pytest tests/test_chunking.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add pyproject.toml odigos/memory/chunking.py tests/test_chunking.py
git commit -m "feat: add ChunkingService with Chonkie for unified intelligent chunking"
```

---

### Task 6: Replace sqlite-vec with ChromaDB

**Files:**
- Modify: `pyproject.toml` (add chromadb, remove sqlite-vec)
- Modify: `odigos/db.py` (remove sqlite-vec extension loading)
- Rewrite: `odigos/memory/vectors.py`
- Modify: `tests/test_vectors.py`
- Delete: `migrations/012_vector_768d.sql`

**Step 1: Update dependencies**

In `pyproject.toml`, replace `sqlite-vec` with `chromadb`:

```toml
# Remove: "sqlite-vec>=0.1.0",
# Add:
"chromadb>=0.5.0",
```

Run: `pip install -e ".[dev]"`

**Step 2: Write the failing test**

Update `tests/test_vectors.py`:

```python
import pytest
from odigos.memory.vectors import VectorMemory, MemoryResult


class TestVectorMemory:
    @pytest.fixture
    async def vector_memory(self, tmp_path):
        """Create a VectorMemory with a test ChromaDB collection."""
        from unittest.mock import AsyncMock

        embedder = AsyncMock()
        embedder.embed.return_value = [0.1] * 768
        embedder.embed_query.return_value = [0.1] * 768

        vm = VectorMemory(embedder=embedder, persist_dir=str(tmp_path / "chroma"))
        await vm.initialize()
        return vm

    async def test_store_and_search(self, vector_memory):
        """Store a document and retrieve it via search."""
        vec_id = await vector_memory.store(
            text="The cat sat on the mat",
            source_type="test",
            source_id="doc-1",
        )
        assert vec_id is not None

        results = await vector_memory.search("cat mat", limit=5)
        assert len(results) >= 1
        assert results[0].content_preview == "The cat sat on the mat"
        assert results[0].source_type == "test"

    async def test_search_empty_collection(self, vector_memory):
        """Search on empty collection returns empty list."""
        results = await vector_memory.search("anything", limit=5)
        assert results == []

    async def test_store_returns_unique_ids(self, vector_memory):
        """Each store call returns a unique vector ID."""
        id1 = await vector_memory.store("text one", "test", "doc-1")
        id2 = await vector_memory.store("text two", "test", "doc-2")
        assert id1 != id2

    async def test_search_respects_limit(self, vector_memory):
        """Search returns at most `limit` results."""
        for i in range(10):
            await vector_memory.store(f"document {i}", "test", f"doc-{i}")

        results = await vector_memory.search("document", limit=3)
        assert len(results) <= 3

    async def test_metadata_filtering(self, vector_memory):
        """Search can filter by source_type metadata."""
        await vector_memory.store("user said hello", "user_message", "conv-1")
        await vector_memory.store("chunk about cats", "document_chunk", "doc-1")

        results = await vector_memory.search("hello", limit=10, source_type="user_message")
        for r in results:
            assert r.source_type == "user_message"
```

**Step 3: Run test to verify it fails**

Run: `pytest tests/test_vectors.py -v`
Expected: FAIL — old VectorMemory expects Database, not persist_dir

**Step 4: Rewrite VectorMemory for ChromaDB**

Rewrite `odigos/memory/vectors.py`:

```python
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

import chromadb

if TYPE_CHECKING:
    from odigos.providers.embeddings import EmbeddingProvider

logger = logging.getLogger(__name__)

COLLECTION_NAME = "memory_vectors"


@dataclass
class MemoryResult:
    content_preview: str
    source_type: str
    source_id: str
    distance: float


class VectorMemory:
    """ChromaDB-backed vector store for semantic memory search."""

    def __init__(self, embedder: EmbeddingProvider, persist_dir: str = "data/chroma") -> None:
        self.embedder = embedder
        self._persist_dir = persist_dir
        self._client: chromadb.ClientAPI | None = None
        self._collection: chromadb.Collection | None = None

    async def initialize(self) -> None:
        """Create or open the ChromaDB persistent client and collection."""
        loop = asyncio.get_running_loop()
        self._client = await loop.run_in_executor(
            None,
            partial(chromadb.PersistentClient, path=self._persist_dir),
        )
        self._collection = await loop.run_in_executor(
            None,
            partial(
                self._client.get_or_create_collection,
                name=COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            ),
        )

    async def store(self, text: str, source_type: str, source_id: str) -> str:
        """Embed text and store in ChromaDB. Returns the vector ID."""
        vector = await self.embedder.embed(text)
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
                }],
                documents=[text[:500]],
            ),
        )
        return vec_id

    async def search(
        self, query: str, limit: int = 5, source_type: str | None = None,
    ) -> list[MemoryResult]:
        """Embed query and find nearest neighbors."""
        # Check collection count first to avoid querying empty collection
        loop = asyncio.get_running_loop()
        count = await loop.run_in_executor(None, self._collection.count)
        if count == 0:
            return []

        vector = await self.embedder.embed_query(query)

        where_filter = None
        if source_type:
            where_filter = {"source_type": source_type}

        results = await loop.run_in_executor(
            None,
            partial(
                self._collection.query,
                query_embeddings=[vector],
                n_results=min(limit, count),
                where=where_filter,
            ),
        )

        memory_results = []
        if results and results["ids"] and results["ids"][0]:
            for i, _id in enumerate(results["ids"][0]):
                meta = results["metadatas"][0][i]
                dist = results["distances"][0][i] if results.get("distances") else 0.0
                memory_results.append(
                    MemoryResult(
                        content_preview=meta.get("content_preview", ""),
                        source_type=meta.get("source_type", ""),
                        source_id=meta.get("source_id", ""),
                        distance=dist,
                    )
                )

        return memory_results
```

**Step 5: Update db.py — remove sqlite-vec**

In `odigos/db.py`, remove the sqlite-vec import and extension loading:

```python
# Remove: import sqlite_vec
# Remove from initialize():
#     await self._conn.enable_load_extension(True)
#     await self._conn.load_extension(sqlite_vec.loadable_path())
#     await self._conn.enable_load_extension(False)
```

**Step 6: Update main.py — pass persist_dir instead of db to VectorMemory**

In `odigos/main.py`, change VectorMemory initialization:

```python
    # Old:
    # vector_memory = VectorMemory(db=_db, embedder=_embedder)

    # New:
    vector_memory = VectorMemory(embedder=_embedder, persist_dir=str(Path(settings.database.path).parent / "chroma"))
```

**Step 7: Run tests to verify they pass**

Run: `pytest tests/test_vectors.py -v`
Expected: PASS

**Step 8: Commit**

```bash
git add pyproject.toml odigos/db.py odigos/memory/vectors.py odigos/main.py tests/test_vectors.py
git commit -m "feat: replace sqlite-vec with ChromaDB for vector storage"
```

---

### Task 7: Wire ChunkingService into MemoryManager and DocumentIngester

**Files:**
- Modify: `odigos/memory/manager.py`
- Modify: `odigos/memory/ingester.py`
- Modify: `odigos/main.py`
- Test: `tests/test_core.py`

**Step 1: Write the failing test**

```python
class TestChunkingIntegration:
    async def test_long_message_is_chunked_before_storage(self, db: Database):
        """Long user messages are chunked before vector storage."""
        from unittest.mock import AsyncMock, call
        from odigos.memory.chunking import ChunkingService
        from odigos.memory.manager import MemoryManager

        vector_memory = AsyncMock()
        vector_memory.store.return_value = "vec-id"
        graph = AsyncMock()
        resolver = AsyncMock()
        summarizer = AsyncMock()
        chunking = ChunkingService()

        mm = MemoryManager(
            vector_memory=vector_memory, graph=graph,
            resolver=resolver, summarizer=summarizer,
            chunking_service=chunking,
        )

        long_msg = "This is a detailed message about cats. " * 200
        await mm.store("c1", long_msg, "response", [])

        # Should have been called multiple times (once per chunk)
        assert vector_memory.store.call_count > 1
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_core.py::TestChunkingIntegration -v`
Expected: FAIL — MemoryManager doesn't accept chunking_service

**Step 3: Implement integration**

In `odigos/memory/manager.py`, add chunking_service parameter and use it:

```python
from odigos.memory.chunking import ChunkingService

class MemoryManager:
    def __init__(
        self,
        vector_memory: VectorMemory,
        graph: EntityGraph,
        resolver: EntityResolver,
        summarizer: ConversationSummarizer,
        chunking_service: ChunkingService | None = None,
    ) -> None:
        self.vector_memory = vector_memory
        self.graph = graph
        self.resolver = resolver
        self.summarizer = summarizer
        self.chunking = chunking_service or ChunkingService()
```

In the `_store_impl` method (or `store` if not yet refactored), replace the single vector store call:

```python
        # 2. Chunk and embed the user message for semantic search
        chunks = self.chunking.chunk(user_message, content_type="message")
        for chunk in chunks:
            await self.vector_memory.store(
                text=chunk,
                source_type="user_message",
                source_id=conversation_id,
            )
```

In `odigos/memory/ingester.py`, use ChunkingService instead of HybridChunker / _split_paragraphs:

```python
from odigos.memory.chunking import ChunkingService

class DocumentIngester:
    def __init__(
        self, db: Database, vector_memory: VectorMemory,
        chunking_service: ChunkingService | None = None,
    ) -> None:
        self.db = db
        self.vector_memory = vector_memory
        self.chunking = chunking_service or ChunkingService()

    async def ingest(self, text: str, filename: str, source_url: str | None = None, dl_doc=None) -> str:
        doc_id = str(uuid.uuid4())

        # Detect content type from filename
        content_type = "document"
        if filename.endswith((".py", ".js", ".ts", ".go", ".rs", ".java", ".c", ".cpp")):
            content_type = "code"

        chunks = self.chunking.chunk(text, content_type=content_type)

        # ... rest of ingestion logic unchanged ...
```

In `odigos/main.py`, create and pass ChunkingService:

```python
    from odigos.memory.chunking import ChunkingService

    chunking_service = ChunkingService()

    # Pass to MemoryManager
    memory_manager = MemoryManager(
        vector_memory=vector_memory,
        graph=graph,
        resolver=resolver,
        summarizer=summarizer,
        chunking_service=chunking_service,
    )

    # Pass to DocumentIngester
    doc_ingester = DocumentIngester(db=_db, vector_memory=vector_memory, chunking_service=chunking_service)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_core.py::TestChunkingIntegration -v`
Expected: PASS

**Step 5: Commit**

```bash
git add odigos/memory/manager.py odigos/memory/ingester.py odigos/main.py tests/test_core.py
git commit -m "feat: wire ChunkingService into MemoryManager and DocumentIngester"
```

---

## Workstream 3: Document Processing

### Task 8: Add MarkItDown and create MarkItDownProvider

**Files:**
- Modify: `pyproject.toml`
- Create: `odigos/providers/markitdown.py`
- Test: `tests/test_markitdown.py`

**Step 1: Add dependency**

In `pyproject.toml`, add:

```toml
"markitdown[all]>=0.1.0",
```

Run: `pip install -e ".[dev]"`

**Step 2: Write the failing test**

Create `tests/test_markitdown.py`:

```python
import pytest
from odigos.providers.markitdown import MarkItDownProvider


class TestMarkItDownProvider:
    def test_convert_text(self):
        """Convert plain text to markdown."""
        provider = MarkItDownProvider()
        result = provider.convert_text("Hello world")
        assert "Hello" in result

    def test_convert_html(self, tmp_path):
        """Convert HTML file to markdown."""
        html = tmp_path / "test.html"
        html.write_text("<h1>Title</h1><p>Content here.</p>")

        provider = MarkItDownProvider()
        result = provider.convert_file(str(html))
        assert "Title" in result
        assert "Content" in result

    def test_convert_nonexistent_file_raises(self):
        """Converting a nonexistent file raises FileNotFoundError."""
        provider = MarkItDownProvider()
        with pytest.raises(FileNotFoundError):
            provider.convert_file("/nonexistent/file.pdf")
```

**Step 3: Run test to verify it fails**

Run: `pytest tests/test_markitdown.py -v`
Expected: FAIL — module doesn't exist

**Step 4: Implement MarkItDownProvider**

Create `odigos/providers/markitdown.py`:

```python
from __future__ import annotations

import logging
from pathlib import Path

from markitdown import MarkItDown

logger = logging.getLogger(__name__)


class MarkItDownProvider:
    """Lightweight document-to-Markdown conversion via Microsoft MarkItDown."""

    def __init__(self) -> None:
        self._converter = MarkItDown()

    def convert_file(self, file_path: str) -> str:
        """Convert a file to Markdown. Raises FileNotFoundError if file doesn't exist."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        result = self._converter.convert(file_path)
        return result.text_content

    def convert_text(self, text: str) -> str:
        """Pass-through for plain text (already Markdown-compatible)."""
        return text

    def convert_url(self, url: str) -> str:
        """Convert a URL's content to Markdown."""
        result = self._converter.convert_url(url)
        return result.text_content
```

**Step 5: Run tests to verify they pass**

Run: `pytest tests/test_markitdown.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add pyproject.toml odigos/providers/markitdown.py tests/test_markitdown.py
git commit -m "feat: add MarkItDownProvider for lightweight document conversion"
```

---

### Task 9: Update DocTool to use MarkItDown as default, Docling as fallback

**Files:**
- Modify: `odigos/tools/document.py`
- Modify: `odigos/main.py`
- Test: `tests/test_doc_tool.py`

**Step 1: Write the failing test**

```python
class TestDocToolMarkItDown:
    async def test_uses_markitdown_by_default(self):
        """DocTool uses MarkItDown when no Docling provider is available."""
        from unittest.mock import AsyncMock, MagicMock
        from odigos.tools.document import DocTool

        markitdown = MagicMock()
        markitdown.convert_file.return_value = "# Converted\n\nContent here."

        ingester = AsyncMock()
        ingester.ingest.return_value = "doc-id"

        tool = DocTool(markitdown_provider=markitdown, ingester=ingester)
        result = await tool.execute({"source": "/tmp/test.pdf"})

        assert result.success
        markitdown.convert_file.assert_called_once()

    async def test_falls_back_to_docling_if_available(self):
        """DocTool uses Docling for complex documents when available."""
        from unittest.mock import AsyncMock, MagicMock
        from odigos.tools.document import DocTool

        markitdown = MagicMock()
        docling = AsyncMock()
        docling.convert.return_value = ("Full content", MagicMock())

        ingester = AsyncMock()
        ingester.ingest.return_value = "doc-id"

        tool = DocTool(
            markitdown_provider=markitdown,
            ingester=ingester,
            docling_provider=docling,
        )
        result = await tool.execute({"source": "/tmp/test.pdf", "deep": True})

        assert result.success
        docling.convert.assert_called_once()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_doc_tool.py::TestDocToolMarkItDown -v`
Expected: FAIL

**Step 3: Update DocTool constructor and execute**

In `odigos/tools/document.py`, update to accept both providers:

```python
class DocTool(BaseTool):
    name = "process_document"
    description = (
        "Process a document (PDF, Word, Excel, HTML, image, etc.) and ingest it into memory. "
        "Pass 'deep: true' for complex PDFs with tables/figures (requires docling plugin)."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "File path or URL to process"},
            "deep": {"type": "boolean", "description": "Use deep extraction (docling) for complex documents. Default false."},
        },
        "required": ["source"],
    }

    def __init__(
        self,
        markitdown_provider=None,
        ingester=None,
        docling_provider=None,
    ) -> None:
        self._markitdown = markitdown_provider
        self._docling = docling_provider
        self._ingester = ingester
```

Update `execute()` to route between MarkItDown and Docling.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_doc_tool.py -v`
Expected: PASS

**Step 5: Update main.py wiring**

Replace direct Docling usage with MarkItDown as default:

```python
    from odigos.providers.markitdown import MarkItDownProvider

    markitdown_provider = MarkItDownProvider()

    # Docling is now optional — check if plugin provides it
    docling_provider = None  # Will be set by plugin if installed

    doc_ingester = DocumentIngester(db=_db, vector_memory=vector_memory, chunking_service=chunking_service)
    doc_tool = DocTool(markitdown_provider=markitdown_provider, ingester=doc_ingester, docling_provider=docling_provider)
```

**Step 6: Commit**

```bash
git add odigos/tools/document.py odigos/main.py tests/test_doc_tool.py
git commit -m "feat: MarkItDown as default document processor, Docling as optional fallback"
```

---

### Task 10: Move Docling to plugin

**Files:**
- Create: `plugins/providers/docling/__init__.py`
- Create: `plugins/providers/docling/plugin.yaml`
- Modify: `pyproject.toml` (remove docling from core deps)
- Test: `tests/test_docling_plugin.py`

**Step 1: Create plugin directory**

```bash
mkdir -p plugins/providers/docling
```

**Step 2: Create plugin module**

Create `plugins/providers/docling/__init__.py`:

```python
"""Docling deep document extraction plugin.

Provides advanced PDF/document processing with table extraction,
figure detection, and layout analysis. Install with:
    pip install docling
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from docling.document_converter import DocumentConverter
except ImportError:
    DocumentConverter = None


class DoclingProvider:
    """Deep document extraction using Docling."""

    def __init__(self) -> None:
        if DocumentConverter is None:
            raise ImportError(
                "Docling is not installed. Install with: pip install docling"
            )
        self._converter = DocumentConverter()

    def convert(self, source: str, max_content_chars: int = 50000) -> tuple[str, object]:
        result = self._converter.convert(source)
        doc = result.document
        content = doc.export_to_markdown()
        if max_content_chars and len(content) > max_content_chars:
            content = content[:max_content_chars] + "\n\n[truncated]"
        return content, doc


def register(ctx):
    """Register the Docling provider as a document processor."""
    try:
        provider = DoclingProvider()
        ctx.register_provider("docling", provider)
        logger.info("Docling plugin loaded")
    except ImportError:
        logger.warning("Docling plugin skipped: docling package not installed")
```

**Step 3: Create plugin.yaml**

Create `plugins/providers/docling/plugin.yaml`:

```yaml
name: docling
description: Deep document extraction with table/figure/layout analysis
version: "1.0.0"
requires:
  - docling>=2.0.0
```

**Step 4: Remove docling from core dependencies**

In `pyproject.toml`, remove:

```toml
# Remove: "docling>=2.0.0",
```

**Step 5: Remove DoclingProvider from core**

Delete `odigos/providers/docling.py` and update any imports.

**Step 6: Commit**

```bash
git add plugins/providers/docling/ pyproject.toml
git rm odigos/providers/docling.py
git commit -m "feat: move Docling to optional plugin, remove from core dependencies"
```

---

## Workstream 4: Plugin Architecture

### Task 11: Create PluginContext and new PluginManager

**Files:**
- Create: `odigos/core/plugin_context.py`
- Modify: `odigos/core/plugins.py`
- Test: `tests/test_plugins.py`

**Step 1: Write the failing test**

```python
class TestPluginContext:
    def test_register_tool(self):
        """PluginContext.register_tool() adds tool to the registry."""
        from odigos.core.plugin_context import PluginContext
        from odigos.tools.registry import ToolRegistry
        from odigos.tools.base import BaseTool, ToolResult

        class DummyTool(BaseTool):
            name = "dummy"
            description = "test"
            async def execute(self, params): return ToolResult(success=True, data="ok")

        tool_registry = ToolRegistry()
        ctx = PluginContext(tool_registry=tool_registry)
        ctx.register_tool(DummyTool())

        assert tool_registry.get("dummy") is not None

    def test_register_provider(self):
        """PluginContext.register_provider() stores provider by name."""
        from odigos.core.plugin_context import PluginContext

        ctx = PluginContext()
        ctx.register_provider("my_llm", object())
        assert ctx.get_provider("my_llm") is not None

    def test_register_channel(self):
        """PluginContext.register_channel() adds to channel registry."""
        from unittest.mock import MagicMock
        from odigos.channels.base import ChannelRegistry
        from odigos.core.plugin_context import PluginContext

        channel_registry = ChannelRegistry()
        ctx = PluginContext(channel_registry=channel_registry)

        mock_channel = MagicMock()
        ctx.register_channel("discord", mock_channel)
        assert channel_registry.for_conversation("discord:123") is not None


class TestPluginLoader:
    def test_loads_register_function_plugins(self, tmp_path):
        """PluginManager loads plugins with register(ctx) pattern."""
        from odigos.core.plugin_context import PluginContext
        from odigos.core.plugins import PluginManager
        from odigos.tools.registry import ToolRegistry

        # Create a test plugin
        plugin_file = tmp_path / "test_plugin.py"
        plugin_file.write_text('''
from odigos.tools.base import BaseTool, ToolResult

class TestTool(BaseTool):
    name = "test_plugin_tool"
    description = "from plugin"
    async def execute(self, params): return ToolResult(success=True, data="ok")

def register(ctx):
    ctx.register_tool(TestTool())
''')

        tool_registry = ToolRegistry()
        ctx = PluginContext(tool_registry=tool_registry)
        manager = PluginManager(plugin_context=ctx)
        manager.load_all(str(tmp_path))

        assert tool_registry.get("test_plugin_tool") is not None

    def test_loads_legacy_hooks_plugins(self, tmp_path):
        """PluginManager still supports legacy hooks-based plugins."""
        from odigos.core.plugin_context import PluginContext
        from odigos.core.plugins import PluginManager
        from odigos.core.trace import Tracer

        plugin_file = tmp_path / "legacy_plugin.py"
        plugin_file.write_text('''
async def on_tool_call(event_type, conversation_id, data):
    pass

hooks = {"tool_call": on_tool_call}
''')

        tracer = Tracer(db=None)
        ctx = PluginContext(tracer=tracer)
        manager = PluginManager(plugin_context=ctx)
        manager.load_all(str(tmp_path))

        assert len(manager.loaded_plugins) == 1
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_plugins.py::TestPluginContext -v && pytest tests/test_plugins.py::TestPluginLoader -v`
Expected: FAIL

**Step 3: Create PluginContext**

Create `odigos/core/plugin_context.py`:

```python
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from odigos.channels.base import Channel, ChannelRegistry
    from odigos.core.trace import Tracer
    from odigos.tools.base import BaseTool
    from odigos.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class PluginContext:
    """Context object passed to plugin register() functions.

    Provides extension points for tools, channels, and providers.
    """

    def __init__(
        self,
        tool_registry: ToolRegistry | None = None,
        channel_registry: ChannelRegistry | None = None,
        tracer: Tracer | None = None,
        config: dict | None = None,
    ) -> None:
        self.tool_registry = tool_registry
        self.channel_registry = channel_registry
        self.tracer = tracer
        self.config = config or {}
        self._providers: dict[str, Any] = {}

    def register_tool(self, tool: BaseTool) -> None:
        """Register a tool into the agent's tool registry."""
        if self.tool_registry is None:
            logger.warning("Cannot register tool '%s': no tool registry", tool.name)
            return
        self.tool_registry.register(tool)
        logger.info("Plugin registered tool: %s", tool.name)

    def register_channel(self, name: str, channel: Channel) -> None:
        """Register a communication channel."""
        if self.channel_registry is None:
            logger.warning("Cannot register channel '%s': no channel registry", name)
            return
        self.channel_registry.register(name, channel)
        logger.info("Plugin registered channel: %s", name)

    def register_provider(self, name: str, provider: Any) -> None:
        """Register a provider (LLM, embedding, vector, document, etc.)."""
        self._providers[name] = provider
        logger.info("Plugin registered provider: %s", name)

    def get_provider(self, name: str) -> Any | None:
        """Retrieve a registered provider by name."""
        return self._providers.get(name)
```

**Step 4: Update PluginManager to support both patterns**

Rewrite `odigos/core/plugins.py`:

```python
from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.core.plugin_context import PluginContext

logger = logging.getLogger(__name__)


class PluginManager:
    """Discovers and loads plugins from a directory.

    Supports two plugin patterns:
    1. New: register(ctx) function — receives PluginContext for registering tools/channels/providers
    2. Legacy: hooks dict — event type -> callback, wired into Tracer
    """

    def __init__(self, plugin_context: PluginContext | None = None, tracer=None) -> None:
        self._ctx = plugin_context
        self._tracer = tracer or (plugin_context.tracer if plugin_context else None)
        self.loaded_plugins: list[dict] = []
        self._plugins_dir: str | None = None
        self._module_names: list[str] = []

    def load_all(self, plugins_dir: str) -> None:
        """Scan plugins_dir for plugin files/directories and load them."""
        for module_name in self._module_names:
            sys.modules.pop(module_name, None)
        self._module_names.clear()
        self.loaded_plugins = []
        self._plugins_dir = plugins_dir
        plugins_path = Path(plugins_dir)
        plugins_path.mkdir(parents=True, exist_ok=True)

        # Load .py files directly
        for py_file in sorted(plugins_path.glob("*.py")):
            if py_file.name.startswith("__"):
                continue
            self._load_plugin(py_file)

        # Load directories with __init__.py
        for subdir in sorted(plugins_path.iterdir()):
            if subdir.is_dir():
                init = subdir / "__init__.py"
                if init.exists():
                    self._load_plugin(init, name_override=subdir.name)

        # Recurse into subdirectories (providers/, tools/, channels/)
        for category_dir in sorted(plugins_path.iterdir()):
            if category_dir.is_dir() and category_dir.name in ("providers", "tools", "channels"):
                for subdir in sorted(category_dir.iterdir()):
                    if subdir.is_dir():
                        init = subdir / "__init__.py"
                        if init.exists():
                            self._load_plugin(init, name_override=subdir.name)
                    elif subdir.suffix == ".py" and not subdir.name.startswith("__"):
                        self._load_plugin(subdir)

    def reload(self) -> None:
        """Clear and reload all plugins."""
        if self._tracer:
            self._tracer.clear_subscribers()
        if self._plugins_dir is not None:
            self.load_all(self._plugins_dir)

    def _load_plugin(self, py_file: Path, name_override: str | None = None) -> None:
        """Import a plugin and register via register(ctx) or legacy hooks."""
        stem = name_override or py_file.stem
        module_name = f"odigos_plugin_{stem}"

        try:
            spec = importlib.util.spec_from_file_location(module_name, py_file)
            if spec is None or spec.loader is None:
                logger.warning("Could not create module spec for %s", py_file)
                return
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        except Exception:
            logger.warning("Failed to import plugin %s", py_file, exc_info=True)
            return

        self._module_names.append(module_name)

        # Try new pattern: register(ctx)
        register_fn = getattr(module, "register", None)
        if register_fn is not None and callable(register_fn) and self._ctx is not None:
            try:
                register_fn(self._ctx)
                self.loaded_plugins.append({"name": stem, "file": str(py_file), "pattern": "register"})
                return
            except Exception:
                logger.warning("Plugin %s register() failed", py_file, exc_info=True)
                return

        # Fall back to legacy pattern: hooks dict
        hooks = getattr(module, "hooks", None)
        if hooks and isinstance(hooks, dict) and self._tracer:
            hook_count = 0
            for event_type, callback in hooks.items():
                if callable(callback):
                    self._tracer.subscribe(event_type, callback)
                    hook_count += 1
            self.loaded_plugins.append({"name": stem, "file": str(py_file), "pattern": "hooks", "hook_count": hook_count})
            return

        logger.warning("Plugin %s has no register() or hooks, skipping", py_file)
```

**Step 5: Run tests to verify they pass**

Run: `pytest tests/test_plugins.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add odigos/core/plugin_context.py odigos/core/plugins.py tests/test_plugins.py
git commit -m "feat: plugin architecture with PluginContext and register(ctx) pattern"
```

---

### Task 12: Wire PluginManager into main.py startup

**Files:**
- Modify: `odigos/main.py`
- Create: `plugins/.gitkeep` (ensure directory exists)

**Step 1: Update main.py plugin loading**

In `odigos/main.py`, replace old PluginManager usage with new pattern:

```python
    from odigos.core.plugin_context import PluginContext

    # Create plugin context with all registries
    plugin_context = PluginContext(
        tool_registry=tool_registry,
        channel_registry=channel_registry,
        tracer=tracer,
        config=settings.model_dump().get("plugins", {}),
    )

    # Load plugins (new register(ctx) pattern + legacy hooks)
    plugin_manager = PluginManager(plugin_context=plugin_context)
    plugin_manager.load_all("plugins")

    # Also load legacy event-hook plugins from data/plugins
    plugin_manager.load_all("data/plugins")

    # Check if docling plugin registered a provider
    docling_provider = plugin_context.get_provider("docling")
    doc_tool = DocTool(
        markitdown_provider=markitdown_provider,
        ingester=doc_ingester,
        docling_provider=docling_provider,
    )
```

Note: Plugin loading must happen **after** tool_registry and channel_registry are created, but **before** the Agent is constructed, so tools from plugins are available to the executor.

**Step 2: Create plugins directory structure**

```bash
mkdir -p plugins/tools plugins/channels plugins/providers
touch plugins/.gitkeep
```

**Step 3: Run full test suite**

Run: `pytest tests/ -v --timeout=30`
Expected: All existing tests pass (no regressions)

**Step 4: Commit**

```bash
git add odigos/main.py plugins/.gitkeep
git commit -m "feat: wire PluginContext and new PluginManager into application startup"
```

---

## Summary

| Task | Workstream | Deliverable |
|------|-----------|-------------|
| 1 | Error Recovery | Executor LLM call error handling |
| 2 | Error Recovery | Embedding failure resilience |
| 3 | Error Recovery | Database retry for SQLITE_BUSY |
| 4 | Error Recovery | Transaction safety for reflector/ingester |
| 5 | Chunking | ChunkingService with Chonkie |
| 6 | Chunking | ChromaDB replaces sqlite-vec |
| 7 | Chunking | Wire chunking into MemoryManager + Ingester |
| 8 | Documents | MarkItDown provider |
| 9 | Documents | DocTool uses MarkItDown default |
| 10 | Documents | Docling moved to plugin |
| 11 | Plugins | PluginContext + updated PluginManager |
| 12 | Plugins | Wire into main.py startup |

**Next plan:** `docs/plans/2026-03-10-phase2-api-websocket-implementation.md` — REST API, unified WebSocket, and Web Channel (workstreams 5-7 from the design doc).
