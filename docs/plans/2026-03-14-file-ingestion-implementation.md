# File Upload Ingestion Pipeline Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Auto-ingest uploaded files into agent memory with provenance tracking and deduplication.

**Architecture:** Wire the existing MarkItDown + DocumentIngester + hybrid search pipeline into the upload endpoint and Telegram channel. Add a migration for provenance columns on the `documents` table. Add source metadata to memory recall results.

**Tech Stack:** Python 3.11+, FastAPI, aiosqlite, MarkItDown, sqlite-vec, FTS5

---

### Task 1: Database Migration — Add Provenance Columns to Documents Table

**Files:**
- Create: `migrations/023_document_provenance.sql`

**Step 1: Write the migration SQL**

```sql
-- Add provenance columns to documents table for upload tracking
ALTER TABLE documents ADD COLUMN conversation_id TEXT;
ALTER TABLE documents ADD COLUMN file_path TEXT;
ALTER TABLE documents ADD COLUMN file_size INTEGER;
ALTER TABLE documents ADD COLUMN content_hash TEXT;
ALTER TABLE documents ADD COLUMN status TEXT NOT NULL DEFAULT 'ingested';

CREATE INDEX IF NOT EXISTS idx_documents_content_hash ON documents(content_hash);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
```

Save this to `migrations/023_document_provenance.sql`.

**Step 2: Verify migration applies**

Run: `cd /Users/jacob/Projects/odigos && python3 -c "import asyncio; from odigos.db import Database; db = Database('data/test_migration.db'); asyncio.run(db.initialize()); print('OK')"`
Expected: OK (no errors)

Clean up: `rm -f data/test_migration.db`

**Step 3: Commit**

```bash
git add migrations/023_document_provenance.sql
git commit -m "feat: add provenance columns to documents table"
```

---

### Task 2: DocumentIngester — Add Deduplication and Provenance

**Files:**
- Modify: `odigos/memory/ingester.py`

**Step 1: Write the failing test**

Create `tests/test_ingester_dedup.py`:

```python
"""Tests for DocumentIngester deduplication and provenance."""

import asyncio
import hashlib
import pytest
from unittest.mock import AsyncMock, MagicMock

# We test against a real SQLite database to avoid mocks
from odigos.db import Database
from odigos.memory.ingester import DocumentIngester


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def db(tmp_path, event_loop):
    db_path = str(tmp_path / "test.db")
    _db = Database(db_path)
    event_loop.run_until_complete(_db.initialize())
    return _db


@pytest.fixture
def fake_vector_memory():
    vm = AsyncMock()
    vm.store = AsyncMock(return_value="vec-id-1")
    vm.delete_by_source = AsyncMock()
    return vm


@pytest.fixture
def fake_chunking():
    cs = MagicMock()
    cs.chunk = MagicMock(return_value=["chunk 1", "chunk 2"])
    return cs


@pytest.fixture
def ingester(db, fake_vector_memory, fake_chunking):
    return DocumentIngester(db=db, vector_memory=fake_vector_memory, chunking_service=fake_chunking)


def test_ingest_creates_document_with_provenance(db, ingester, event_loop):
    """Ingest should store file_path, file_size, content_hash, conversation_id."""
    doc_id = event_loop.run_until_complete(
        ingester.ingest(
            text="hello world",
            filename="report.pdf",
            file_path="/data/uploads/abc_report.pdf",
            file_size=1024,
            content_hash=hashlib.sha256(b"hello world").hexdigest(),
            conversation_id="conv-123",
        )
    )
    row = event_loop.run_until_complete(
        db.fetch_one("SELECT * FROM documents WHERE id = ?", (doc_id,))
    )
    assert row is not None
    assert row["file_path"] == "/data/uploads/abc_report.pdf"
    assert row["file_size"] == 1024
    assert row["content_hash"] is not None
    assert row["conversation_id"] == "conv-123"
    assert row["status"] == "ingested"


def test_ingest_deduplicates_by_filename(db, ingester, fake_vector_memory, event_loop):
    """Re-ingesting same filename should delete old chunks and replace."""
    doc_id_1 = event_loop.run_until_complete(
        ingester.ingest(text="version 1", filename="report.pdf")
    )
    doc_id_2 = event_loop.run_until_complete(
        ingester.ingest(text="version 2", filename="report.pdf")
    )
    assert doc_id_1 != doc_id_2

    # Old document should be deleted
    old_row = event_loop.run_until_complete(
        db.fetch_one("SELECT * FROM documents WHERE id = ?", (doc_id_1,))
    )
    assert old_row is None

    # New document should exist
    new_row = event_loop.run_until_complete(
        db.fetch_one("SELECT * FROM documents WHERE id = ?", (doc_id_2,))
    )
    assert new_row is not None

    # delete_by_source should have been called for old doc
    fake_vector_memory.delete_by_source.assert_called_once_with("document_chunk", doc_id_1)


def test_ingest_exact_duplicate_skipped(db, ingester, event_loop):
    """If content_hash matches existing document, skip re-ingestion."""
    content = "identical content"
    content_hash = hashlib.sha256(content.encode()).hexdigest()

    doc_id_1 = event_loop.run_until_complete(
        ingester.ingest(text=content, filename="report.pdf", content_hash=content_hash)
    )
    doc_id_2 = event_loop.run_until_complete(
        ingester.ingest(text=content, filename="report.pdf", content_hash=content_hash)
    )
    # Same document returned (no re-ingestion)
    assert doc_id_1 == doc_id_2


def test_ingest_sets_status_failed_on_error(db, ingester, fake_vector_memory, event_loop):
    """If all chunks fail to store, status should be 'failed'."""
    fake_vector_memory.store = AsyncMock(side_effect=Exception("embed error"))

    doc_id = event_loop.run_until_complete(
        ingester.ingest(text="will fail", filename="bad.pdf")
    )
    row = event_loop.run_until_complete(
        db.fetch_one("SELECT status, chunk_count FROM documents WHERE id = ?", (doc_id,))
    )
    assert row["status"] == "failed"
    assert row["chunk_count"] == 0
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_ingester_dedup.py -v`
Expected: FAIL — `ingest()` doesn't accept `file_path`, `content_hash`, etc.

**Step 3: Update DocumentIngester**

Modify `odigos/memory/ingester.py` to replace the entire file:

```python
from __future__ import annotations

import logging
import uuid
from odigos.db import Database
from odigos.memory.chunking import ChunkingService
from odigos.memory.vectors import VectorMemory

logger = logging.getLogger(__name__)


class DocumentIngester:
    """Chunks and embeds documents into VectorMemory for RAG retrieval."""

    def __init__(
        self, db: Database, vector_memory: VectorMemory,
        chunking_service: ChunkingService | None = None,
    ) -> None:
        self.db = db
        self.vector_memory = vector_memory
        self.chunking = chunking_service or ChunkingService()

    async def ingest(
        self,
        text: str,
        filename: str,
        source_url: str | None = None,
        file_path: str | None = None,
        file_size: int | None = None,
        content_hash: str | None = None,
        conversation_id: str | None = None,
    ) -> str:
        """Ingest a document: chunk, embed, store with provenance.

        If a document with the same filename already exists:
        - If content_hash matches, skip (return existing doc ID).
        - Otherwise, delete old chunks and replace.
        """
        # Check for existing document with same filename
        existing = await self.db.fetch_one(
            "SELECT id, content_hash FROM documents WHERE filename = ? ORDER BY ingested_at DESC LIMIT 1",
            (filename,),
        )

        if existing:
            # Exact duplicate — same file, same content
            if content_hash and existing["content_hash"] == content_hash:
                logger.info("Skipping duplicate document '%s' (hash match)", filename)
                return existing["id"]

            # Same filename, different content — replace old version
            logger.info("Replacing existing document '%s' (id=%s)", filename, existing["id"])
            await self.vector_memory.delete_by_source("document_chunk", existing["id"])
            await self.db.execute("DELETE FROM documents WHERE id = ?", (existing["id"],))

        doc_id = str(uuid.uuid4())

        # Detect content type from filename
        content_type = "document"
        if filename.endswith((".py", ".js", ".ts", ".go", ".rs", ".java", ".c", ".cpp")):
            content_type = "code"

        chunks = self.chunking.chunk(text, content_type=content_type)

        # Insert document record with provenance (status=processing)
        await self.db.execute(
            "INSERT INTO documents (id, filename, source_url, chunk_count, file_path, file_size, content_hash, conversation_id, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (doc_id, filename, source_url, 0, file_path, file_size, content_hash, conversation_id, "processing"),
        )

        stored_count = 0
        for chunk_text in chunks:
            try:
                await self.vector_memory.store(
                    text=chunk_text,
                    source_type="document_chunk",
                    source_id=doc_id,
                    when_to_use=f"when referencing content from '{filename}': {chunk_text[:100]}",
                )
                stored_count += 1
            except Exception:
                logger.warning(
                    "Failed to store chunk %d/%d for document %s",
                    stored_count + 1, len(chunks), doc_id, exc_info=True,
                )
                break

        # Update with actual stored chunk count and final status
        status = "ingested" if stored_count > 0 else "failed"
        await self.db.execute(
            "UPDATE documents SET chunk_count = ?, status = ? WHERE id = ?",
            (stored_count, status, doc_id),
        )

        logger.info(
            "Ingested document '%s' (%d/%d chunks, status=%s) as %s",
            filename, stored_count, len(chunks), status, doc_id,
        )
        return doc_id

    async def delete(self, document_id: str) -> None:
        """Delete a document and all its chunks from vector memory."""
        row = await self.db.fetch_one(
            "SELECT chunk_count FROM documents WHERE id = ?",
            (document_id,),
        )
        chunk_count = row["chunk_count"] if row else 0

        await self.vector_memory.delete_by_source("document_chunk", document_id)

        await self.db.execute(
            "DELETE FROM documents WHERE id = ?",
            (document_id,),
        )

        logger.info("Deleted document %s (%d chunks)", document_id, chunk_count)

    async def get_document_metadata(self, document_id: str) -> dict | None:
        """Look up document provenance by ID."""
        row = await self.db.fetch_one(
            "SELECT id, filename, file_path, file_size, content_hash, "
            "conversation_id, source_url, chunk_count, status, ingested_at "
            "FROM documents WHERE id = ?",
            (document_id,),
        )
        return dict(row) if row else None
```

**Step 4: Run tests to verify they pass**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_ingester_dedup.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add odigos/memory/ingester.py tests/test_ingester_dedup.py
git commit -m "feat: add deduplication and provenance to DocumentIngester"
```

---

### Task 3: Wire Ingestion Into Upload Endpoint

**Files:**
- Modify: `odigos/api/upload.py`
- Modify: `odigos/api/deps.py` (add `get_doc_ingester` and `get_markitdown` helpers)
- Modify: `odigos/main.py` (expose ingester and markitdown on app.state)

**Step 1: Add dependency accessors to deps.py**

Add to the end of `odigos/api/deps.py`:

```python
def get_doc_ingester(request: Request):
    """Get the DocumentIngester instance from app state."""
    return request.app.state.doc_ingester


def get_markitdown(request: Request):
    """Get the MarkItDownProvider instance from app state."""
    return request.app.state.markitdown_provider
```

**Step 2: Expose ingester and markitdown on app.state in main.py**

In `odigos/main.py`, after line 230 where `doc_ingester` is created, add:

```python
    app.state.doc_ingester = doc_ingester
    app.state.markitdown_provider = markitdown_provider
```

**Step 3: Rewrite upload.py with auto-ingestion**

Replace `odigos/api/upload.py` with:

```python
"""File upload endpoint with auto-ingestion into agent memory."""

import asyncio
import hashlib
import os
import secrets

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from odigos.api.deps import get_doc_ingester, get_markitdown, get_upload_dir, require_api_key
from odigos.memory.ingester import DocumentIngester
from odigos.providers.markitdown import MarkItDownProvider

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB
PREVIEW_CHARS = 2000

router = APIRouter(
    prefix="/api",
    dependencies=[Depends(require_api_key)],
)


@router.post("/upload")
async def upload_file(
    file: UploadFile,
    upload_dir: str = Depends(get_upload_dir),
    ingester: DocumentIngester = Depends(get_doc_ingester),
    markitdown: MarkItDownProvider = Depends(get_markitdown),
):
    """Upload a file, auto-ingest into memory, return metadata + content preview."""
    os.makedirs(upload_dir, exist_ok=True)

    file_id = secrets.token_hex(8)
    safe_name = os.path.basename(file.filename or "upload")
    dest = os.path.join(upload_dir, f"{file_id}_{safe_name}")

    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (50 MB max)")

    with open(dest, "wb") as f:
        f.write(content)

    content_hash = hashlib.sha256(content).hexdigest()

    # Extract text via MarkItDown
    extracted_text = None
    chunk_count = 0
    status = "failed"
    doc_id = None

    try:
        extracted_text = await asyncio.to_thread(markitdown.convert_file, dest)
    except Exception:
        pass  # Non-extractable file (binary, corrupted, etc.)

    if extracted_text:
        try:
            doc_id = await ingester.ingest(
                text=extracted_text,
                filename=safe_name,
                file_path=dest,
                file_size=len(content),
                content_hash=content_hash,
            )
            row = await ingester.get_document_metadata(doc_id)
            if row:
                chunk_count = row["chunk_count"]
                status = row["status"]
        except Exception:
            status = "failed"

    return {
        "id": file_id,
        "document_id": doc_id,
        "filename": file.filename,
        "size": len(content),
        "chunk_count": chunk_count,
        "status": status,
        "content_preview": extracted_text[:PREVIEW_CHARS] if extracted_text else None,
    }
```

**Step 4: Verify upload with ingestion works**

Rebuild containers and test:
```bash
docker compose -f docker-compose.test.yml up --build -d
# Wait for healthy
curl -sf -H "Authorization: Bearer alice-test-key" \
  -F "file=@README.md" \
  http://localhost:8100/api/upload | python3 -m json.tool
```

Expected: Response includes `document_id`, `chunk_count > 0`, `status: "ingested"`, and a `content_preview`.

**Step 5: Commit**

```bash
git add odigos/api/upload.py odigos/api/deps.py odigos/main.py
git commit -m "feat: auto-ingest uploaded files into agent memory"
```

---

### Task 4: Wire Ingestion Into Telegram Channel

**Files:**
- Modify: `odigos/channels/telegram.py`

**Step 1: Read current Telegram channel to understand service interface**

The Telegram handler at `odigos/channels/telegram.py:127-177` downloads files to `/tmp/odigos/` and passes the path via `message.metadata["file_path"]`. The `self.service` is the `AgentService` — check how it provides access to the ingester.

Check: `grep -n "class AgentService" odigos/core/service.py` to find the service class and see what's available.

**Step 2: Copy file to persistent upload dir and auto-ingest**

Modify `_handle_document` in `odigos/channels/telegram.py`. After downloading the file (line 147), add:

```python
        # Copy to persistent uploads directory and auto-ingest
        import hashlib
        import shutil

        upload_dir = getattr(self.service, "upload_dir", "data/uploads")
        os.makedirs(upload_dir, exist_ok=True)
        persistent_path = os.path.join(upload_dir, os.path.basename(file_path))
        shutil.copy2(file_path, persistent_path)

        # Auto-ingest into memory
        ingester = getattr(self.service, "doc_ingester", None)
        markitdown = getattr(self.service, "markitdown_provider", None)
        if ingester and markitdown:
            try:
                import asyncio

                with open(persistent_path, "rb") as fh:
                    file_bytes = fh.read()
                content_hash = hashlib.sha256(file_bytes).hexdigest()

                extracted = await asyncio.to_thread(
                    markitdown.convert_file, persistent_path
                )
                if extracted:
                    await ingester.ingest(
                        text=extracted,
                        filename=os.path.basename(file_path),
                        file_path=persistent_path,
                        file_size=len(file_bytes),
                        content_hash=content_hash,
                    )
            except Exception:
                logger.warning("Auto-ingestion failed for %s", file_path, exc_info=True)
```

This requires that `AgentService` exposes `doc_ingester`, `markitdown_provider`, and `upload_dir`. Check the service class and add these attributes if they're not already there.

**Step 3: Verify the Telegram handler change**

This requires a running Telegram bot. Verify by checking:
```bash
python3 -c "from odigos.channels.telegram import TelegramChannel; print('import OK')"
```

**Step 4: Commit**

```bash
git add odigos/channels/telegram.py
git commit -m "feat: auto-ingest Telegram file uploads into memory"
```

---

### Task 5: Add Source Metadata to Memory Recall

**Files:**
- Modify: `odigos/memory/manager.py`
- Modify: `odigos/memory/ingester.py` (already has `get_document_metadata`)

**Step 1: Write the failing test**

Create `tests/test_recall_provenance.py`:

```python
"""Test that memory recall includes source document metadata."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from odigos.memory.manager import MemoryManager
from odigos.memory.vectors import MemoryResult


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def test_recall_includes_document_source(event_loop):
    """When a recalled memory is a document_chunk, include filename in output."""
    mock_vector = AsyncMock()
    mock_vector.search = AsyncMock(return_value=[
        MemoryResult(
            content_preview="Revenue grew 15% year-over-year",
            source_type="document_chunk",
            source_id="doc-123",
            distance=0.1,
            when_to_use="when referencing content from 'quarterly-report.pdf'",
        )
    ])
    mock_vector.search_fts = AsyncMock(return_value=[])

    mock_graph = AsyncMock()
    mock_graph.find_entity = AsyncMock(return_value=[])

    manager = MemoryManager(
        vector_memory=mock_vector,
        graph=mock_graph,
        resolver=AsyncMock(),
        summarizer=AsyncMock(),
    )

    result = event_loop.run_until_complete(manager.recall("revenue growth"))
    assert "quarterly-report.pdf" in result
```

**Step 2: Run test to verify it fails (or passes — when_to_use already contains filename)**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_recall_provenance.py -v`

If it already passes because `when_to_use` contains the filename from Task 2's ingester changes, great — the provenance is already surfaced through the existing `when_to_use` field. No further changes needed to the recall path.

If it fails, modify `MemoryManager.recall()` to extract source info from `when_to_use` or do a document lookup.

**Step 3: Enhance recall output format for document chunks**

In `odigos/memory/manager.py`, update the recall method's memory formatting (around line 68-69):

Change:
```python
            if result.source_type != "entity_name":
                memory_lines.append(f"- {result.content_preview}")
```

To:
```python
            if result.source_type == "document_chunk" and result.when_to_use:
                # Extract filename from when_to_use pattern
                source_hint = ""
                if "from '" in result.when_to_use:
                    source_hint = result.when_to_use.split("from '")[1].split("'")[0]
                if source_hint:
                    memory_lines.append(f"- [Source: {source_hint}] {result.content_preview}")
                else:
                    memory_lines.append(f"- {result.content_preview}")
            elif result.source_type != "entity_name":
                memory_lines.append(f"- {result.content_preview}")
```

**Step 4: Run tests**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_recall_provenance.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add odigos/memory/manager.py tests/test_recall_provenance.py
git commit -m "feat: include source filename in memory recall for document chunks"
```

---

### Task 6: Update DocTool to Pass Provenance

**Files:**
- Modify: `odigos/tools/document.py`

**Step 1: Update DocTool._ingest to pass provenance fields**

The `process_document` tool currently calls `ingester.ingest(text, filename, source_url)` without the new provenance fields. Update `_ingest` in `odigos/tools/document.py`:

Change the `_ingest` method:

```python
    async def _ingest(self, source: str, content: str) -> None:
        if not self.ingester:
            return
        try:
            import hashlib
            import os

            filename = source.rsplit("/", 1)[-1] if "/" in source else source
            source_url = source if source.startswith(("http://", "https://")) else None
            file_path = source if not source.startswith(("http://", "https://")) else None
            file_size = os.path.getsize(source) if file_path and os.path.exists(source) else None
            content_hash = hashlib.sha256(content.encode()).hexdigest()

            await self.ingester.ingest(
                text=content,
                filename=filename,
                source_url=source_url,
                file_path=file_path,
                file_size=file_size,
                content_hash=content_hash,
            )
        except Exception as e:
            logger.warning("Document ingestion failed for %s: %s", source, e, exc_info=True)
```

**Step 2: Verify import works**

Run: `cd /Users/jacob/Projects/odigos && python3 -c "from odigos.tools.document import DocTool; print('OK')"`
Expected: OK

**Step 3: Commit**

```bash
git add odigos/tools/document.py
git commit -m "feat: pass provenance metadata through DocTool ingestion"
```

---

### Task 7: Integration Test — End-to-End Upload + Recall

**Files:**
- Create: `tests/test_upload_integration.py`

**Step 1: Write integration test**

```python
"""End-to-end test: upload a file via API, verify it's ingested, recall it."""

import asyncio
import os
import tempfile
import pytest

from odigos.db import Database
from odigos.memory.chunking import ChunkingService
from odigos.memory.ingester import DocumentIngester
from odigos.memory.vectors import VectorMemory
from odigos.providers.embeddings import EmbeddingProvider
from odigos.providers.markitdown import MarkItDownProvider


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def db(tmp_path, event_loop):
    db_path = str(tmp_path / "test.db")
    _db = Database(db_path)
    event_loop.run_until_complete(_db.initialize())
    return _db


def test_text_file_upload_and_recall(db, tmp_path, event_loop):
    """Upload a .txt file, ingest it, search for it in memory."""
    # Create a test file
    test_file = tmp_path / "meeting-notes.txt"
    test_file.write_text(
        "Meeting notes from March 14 standup:\n"
        "- Alice presented the new dashboard design\n"
        "- Bob reported the API latency fix is deployed\n"
        "- Next sprint focus: file upload ingestion pipeline\n"
    )

    markitdown = MarkItDownProvider()
    embedder = EmbeddingProvider()
    vector_memory = VectorMemory(embedder=embedder, db=db)
    chunking = ChunkingService()
    ingester = DocumentIngester(db=db, vector_memory=vector_memory, chunking_service=chunking)

    # Extract and ingest
    extracted = markitdown.convert_file(str(test_file))
    assert "dashboard design" in extracted

    doc_id = event_loop.run_until_complete(
        ingester.ingest(
            text=extracted,
            filename="meeting-notes.txt",
            file_path=str(test_file),
            file_size=test_file.stat().st_size,
        )
    )

    # Verify document record
    row = event_loop.run_until_complete(
        db.fetch_one("SELECT * FROM documents WHERE id = ?", (doc_id,))
    )
    assert row is not None
    assert row["filename"] == "meeting-notes.txt"
    assert row["status"] == "ingested"
    assert row["chunk_count"] > 0

    # Search memory for content
    results = event_loop.run_until_complete(
        vector_memory.search("dashboard design", limit=3)
    )
    assert len(results) > 0
    assert any("dashboard" in r.content_preview.lower() for r in results)
    assert results[0].source_type == "document_chunk"
    assert results[0].source_id == doc_id


def test_duplicate_upload_replaces(db, tmp_path, event_loop):
    """Re-uploading same filename with different content replaces old version."""
    embedder = EmbeddingProvider()
    vector_memory = VectorMemory(embedder=embedder, db=db)
    chunking = ChunkingService()
    ingester = DocumentIngester(db=db, vector_memory=vector_memory, chunking_service=chunking)

    # First upload
    doc_id_1 = event_loop.run_until_complete(
        ingester.ingest(text="Version 1 content about cats", filename="doc.txt")
    )

    # Second upload (same filename, different content)
    doc_id_2 = event_loop.run_until_complete(
        ingester.ingest(text="Version 2 content about dogs", filename="doc.txt")
    )

    assert doc_id_1 != doc_id_2

    # Only new document should exist
    rows = event_loop.run_until_complete(
        db.fetch_all("SELECT id FROM documents WHERE filename = 'doc.txt'")
    )
    assert len(rows) == 1
    assert rows[0]["id"] == doc_id_2

    # Search should find new content, not old
    results = event_loop.run_until_complete(
        vector_memory.search("dogs", limit=3)
    )
    assert len(results) > 0
    assert results[0].source_id == doc_id_2
```

**Step 2: Run integration tests**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_upload_integration.py -v`

Note: This requires `sentence-transformers` to be installed for embedding. If running locally without the model, skip this test and verify via the Docker containers instead.

**Step 3: Commit**

```bash
git add tests/test_upload_integration.py
git commit -m "test: add integration tests for file upload ingestion pipeline"
```

---

### Task 8: Manual Verification via Docker Containers

**No code changes — verification only.**

**Step 1: Rebuild and restart containers**

```bash
docker compose -f docker-compose.test.yml up --build -d
# Wait for healthy
docker compose -f docker-compose.test.yml ps
```

**Step 2: Test upload with ingestion**

```bash
# Upload a text file
echo "Important: The project deadline is April 15th. Budget is $50,000." > /tmp/test-doc.txt
curl -sf -H "Authorization: Bearer alice-test-key" \
  -F "file=@/tmp/test-doc.txt" \
  http://localhost:8100/api/upload | python3 -m json.tool
```

Expected: `chunk_count > 0`, `status: "ingested"`, `content_preview` contains the text.

**Step 3: Verify memory recall finds the content**

```bash
curl -sf -H "Authorization: Bearer alice-test-key" \
  "http://localhost:8100/api/memory/search?q=project+deadline" | python3 -m json.tool
```

Expected: Results include content from the uploaded file.

**Step 4: Test deduplication**

```bash
# Upload same filename with different content
echo "Updated: The project deadline moved to May 1st. Budget increased to $75,000." > /tmp/test-doc.txt
curl -sf -H "Authorization: Bearer alice-test-key" \
  -F "file=@/tmp/test-doc.txt" \
  http://localhost:8100/api/upload | python3 -m json.tool
```

Expected: New `document_id`, old chunks replaced.

**Step 5: Test agent can reference uploaded content**

```bash
curl -sf -H "Authorization: Bearer alice-test-key" -H "Content-Type: application/json" \
  -d '{"content":"What do you know about our project deadline?"}' \
  http://localhost:8100/api/message | python3 -m json.tool
```

Expected: Agent references the uploaded document content in its response.

**Step 6: Test provenance**

```bash
curl -sf -H "Authorization: Bearer alice-test-key" -H "Content-Type: application/json" \
  -d '{"content":"Where did you learn about the project deadline? What was the source?"}' \
  http://localhost:8100/api/message | python3 -m json.tool
```

Expected: Agent mentions the source file name.
