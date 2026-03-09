# RAG Document Ingestion Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make every document the agent reads permanently searchable via the existing vector memory pipeline.

**Architecture:** Enhance `DoclingProvider` to expose the raw `DoclingDocument` for chunking. A new `DocumentIngester` uses Docling's `HybridChunker` to split documents into structural chunks, embeds each via `VectorMemory`, and tracks metadata in a `documents` table. `DocTool` gains ingestion as a side effect -- read AND store in one step. Retrieval is automatic via existing `recall()`.

**Tech Stack:** Python 3.12, docling (HybridChunker), sqlite-vec, asyncio

**Design doc:** `docs/plans/2026-03-09-rag-ingestion-design.md`

---

### Task 1: Database migration and DocumentIngester

**Files:**
- Create: `migrations/010_documents.sql`
- Create: `odigos/memory/ingester.py`
- Create: `tests/test_ingester.py`

**Context:** The `DocumentIngester` orchestrates: chunking -> embedding -> storage. It uses Docling's `HybridChunker` to split text structurally, stores each chunk in `VectorMemory` with `source_type="document_chunk"`, and creates a parent record in the `documents` table.

`VectorMemory` (at `odigos/memory/vectors.py`) has `store(text, source_type, source_id) -> str` and `search(query, limit) -> list[MemoryResult]`.

The `HybridChunker` from docling works on `DoclingDocument` objects. Since we also need to support plain text ingestion (not just docling-converted docs), the ingester should accept either a `DoclingDocument` or fall back to simple paragraph splitting for raw text.

**Step 1: Create migration**

Create `migrations/010_documents.sql`:

```sql
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    source_url TEXT,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    ingested_at TEXT DEFAULT (datetime('now'))
);
```

**Step 2: Write the tests**

Create `tests/test_ingester.py`:

```python
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from odigos.memory.ingester import DocumentIngester


class TestDocumentIngester:
    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.execute = AsyncMock()
        db.fetch_one = AsyncMock(return_value=None)
        return db

    @pytest.fixture
    def mock_vector_memory(self):
        vm = AsyncMock()
        vm.store = AsyncMock(return_value=str(uuid.uuid4()))
        return vm

    @pytest.fixture
    def ingester(self, mock_db, mock_vector_memory):
        return DocumentIngester(db=mock_db, vector_memory=mock_vector_memory)

    async def test_ingest_stores_chunks(self, ingester, mock_vector_memory):
        text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        doc_id = await ingester.ingest(text=text, filename="test.txt")

        assert doc_id is not None
        assert mock_vector_memory.store.call_count > 0
        # All chunks stored with source_type="document_chunk"
        for call in mock_vector_memory.store.call_args_list:
            assert call.kwargs.get("source_type") or call.args[1] == "document_chunk"

    async def test_ingest_creates_document_record(self, ingester, mock_db):
        await ingester.ingest(text="Some content.", filename="doc.pdf")

        # Should INSERT into documents table
        insert_calls = [
            c for c in mock_db.execute.call_args_list
            if "INSERT INTO documents" in str(c)
        ]
        assert len(insert_calls) == 1

    async def test_ingest_with_source_url(self, ingester, mock_db):
        await ingester.ingest(
            text="Content.", filename="remote.pdf",
            source_url="https://example.com/remote.pdf",
        )

        insert_call = [
            c for c in mock_db.execute.call_args_list
            if "INSERT INTO documents" in str(c)
        ][0]
        # source_url should be in the params
        assert "https://example.com/remote.pdf" in str(insert_call)

    async def test_ingest_returns_document_id(self, ingester):
        doc_id = await ingester.ingest(text="Content.", filename="test.txt")
        assert isinstance(doc_id, str)
        # Should be a valid UUID
        uuid.UUID(doc_id)

    async def test_ingest_chunk_count(self, ingester, mock_db):
        text = "Para one.\n\nPara two.\n\nPara three."
        await ingester.ingest(text=text, filename="test.txt")

        insert_call = [
            c for c in mock_db.execute.call_args_list
            if "INSERT INTO documents" in str(c)
        ][0]
        # chunk_count param should be > 0
        params = insert_call.args[1] if len(insert_call.args) > 1 else insert_call[0][1]
        # The chunk_count should be a positive integer in the params tuple
        assert any(isinstance(p, int) and p > 0 for p in params)

    async def test_ingest_empty_text(self, ingester):
        doc_id = await ingester.ingest(text="", filename="empty.txt")
        assert doc_id is not None
        # Should still create a record but with 0 chunks

    async def test_delete_document(self, ingester, mock_db, mock_vector_memory):
        mock_db.fetch_all = AsyncMock(return_value=[
            {"source_id": "chunk-1"},
            {"source_id": "chunk-2"},
        ])
        mock_vector_memory.delete = AsyncMock()

        await ingester.delete("doc-123")

        # Should delete from documents table and vector memory
        delete_calls = [
            c for c in mock_db.execute.call_args_list
            if "DELETE" in str(c)
        ]
        assert len(delete_calls) >= 1

    async def test_ingest_with_docling_document(self, ingester, mock_vector_memory):
        """When a DoclingDocument is provided, use HybridChunker."""
        mock_doc = MagicMock()
        mock_chunk = MagicMock()
        mock_chunk.text = "Chunk from docling"

        with patch("odigos.memory.ingester.HybridChunker") as MockChunker:
            MockChunker.return_value.chunk.return_value = [mock_chunk]
            doc_id = await ingester.ingest(
                text="fallback",
                filename="test.pdf",
                dl_doc=mock_doc,
            )

        assert doc_id is not None
        MockChunker.return_value.chunk.assert_called_once_with(mock_doc)
        mock_vector_memory.store.assert_called_once()
        assert "Chunk from docling" in str(mock_vector_memory.store.call_args)
```

**Step 3: Run tests to verify they fail**

Run: `pytest tests/test_ingester.py -v`
Expected: FAIL (`odigos.memory.ingester` does not exist)

**Step 4: Implement DocumentIngester**

Create `odigos/memory/ingester.py`:

```python
from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from odigos.db import Database
from odigos.memory.vectors import VectorMemory

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _split_paragraphs(text: str) -> list[str]:
    """Simple fallback chunker: split on double newlines, skip empties."""
    chunks = [p.strip() for p in text.split("\n\n") if p.strip()]
    return chunks if chunks else [text] if text.strip() else []


class DocumentIngester:
    """Chunks and embeds documents into VectorMemory for RAG retrieval."""

    def __init__(self, db: Database, vector_memory: VectorMemory) -> None:
        self.db = db
        self.vector_memory = vector_memory

    async def ingest(
        self,
        text: str,
        filename: str,
        source_url: str | None = None,
        dl_doc=None,
    ) -> str:
        """Chunk and embed a document.

        Args:
            text: Extracted document text (fallback for chunking).
            filename: Display name for the document.
            source_url: Optional source URL.
            dl_doc: Optional DoclingDocument for structural chunking.

        Returns:
            The document ID.
        """
        doc_id = str(uuid.uuid4())

        # Chunk using Docling's HybridChunker if DoclingDocument available,
        # otherwise fall back to paragraph splitting
        if dl_doc is not None:
            try:
                from docling.chunking import HybridChunker
                chunker = HybridChunker()
                chunks = [c.text for c in chunker.chunk(dl_doc) if c.text.strip()]
            except ImportError:
                logger.warning("docling chunker not available, falling back to paragraph split")
                chunks = _split_paragraphs(text)
        else:
            chunks = _split_paragraphs(text)

        # Embed and store each chunk
        for chunk_text in chunks:
            await self.vector_memory.store(
                text=chunk_text,
                source_type="document_chunk",
                source_id=doc_id,
            )

        # Create document record
        await self.db.execute(
            "INSERT INTO documents (id, filename, source_url, chunk_count) "
            "VALUES (?, ?, ?, ?)",
            (doc_id, filename, source_url, len(chunks)),
        )

        logger.info(
            "Ingested document '%s' (%d chunks) as %s",
            filename, len(chunks), doc_id,
        )
        return doc_id

    async def delete(self, document_id: str) -> None:
        """Delete a document and all its chunks from vector memory."""
        # Find all vector entries for this document
        rows = await self.db.fetch_all(
            "SELECT id FROM memory_vectors WHERE source_type = 'document_chunk' AND source_id = ?",
            (document_id,),
        )

        for row in rows:
            await self.db.execute(
                "DELETE FROM memory_vectors WHERE id = ?",
                (row["id"],),
            )

        await self.db.execute(
            "DELETE FROM documents WHERE id = ?",
            (document_id,),
        )

        logger.info("Deleted document %s (%d chunks)", document_id, len(rows))
```

**Step 5: Run tests to verify they pass**

Run: `pytest tests/test_ingester.py -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add migrations/010_documents.sql odigos/memory/ingester.py tests/test_ingester.py
git commit -m "feat: add DocumentIngester with chunking and vector storage"
```

---

### Task 2: Enhance DoclingProvider and DocTool

**Files:**
- Modify: `odigos/providers/docling.py`
- Modify: `odigos/tools/document.py`
- Modify: `tests/test_ingester.py` (add integration-style test)

**Context:** `DoclingProvider.convert()` currently throws away the `DoclingDocument` and only returns markdown. We need to expose it so the chunker can use it. Then `DocTool` needs to call `DocumentIngester.ingest()` after conversion, passing the `DoclingDocument`.

**Step 1: Update DoclingProvider to return DoclingDocument**

In `odigos/providers/docling.py`, add the `dl_doc` field to `ConvertedDocument` and populate it:

```python
@dataclass
class ConvertedDocument:
    source: str
    content: str
    dl_doc: object = None  # DoclingDocument for chunking
```

In `convert()`, store the document:

```python
    def convert(self, source: str) -> ConvertedDocument:
        result = self._converter.convert(source)
        dl_doc = result.document
        content = dl_doc.export_to_markdown()

        if len(content) > self.max_content_chars:
            content = content[: self.max_content_chars] + "\n\n[truncated]"

        return ConvertedDocument(source=source, content=content, dl_doc=dl_doc)
```

**Step 2: Update DocTool to ingest after reading**

In `odigos/tools/document.py`, add `DocumentIngester` as a constructor dependency:

```python
class DocTool(BaseTool):
    """Convert a document (PDF, DOCX, PPTX, image) to readable text."""

    name = "read_document"
    description = "Convert a document (PDF, DOCX, PPTX, image) to readable text. The document is automatically ingested into memory for future reference."
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path or URL to the document"},
        },
        "required": ["path"],
    }

    def __init__(self, provider: DoclingProvider, ingester: DocumentIngester | None = None) -> None:
        self.provider = provider
        self.ingester = ingester

    async def execute(self, params: dict) -> ToolResult:
        source = params.get("path") or params.get("url")
        if not source:
            return ToolResult(success=False, data="", error="No path or url provided")

        try:
            result = await asyncio.to_thread(self.provider.convert, source)

            # Ingest for future retrieval
            if self.ingester:
                filename = source.rsplit("/", 1)[-1] if "/" in source else source
                source_url = source if source.startswith(("http://", "https://")) else None
                await self.ingester.ingest(
                    text=result.content,
                    filename=filename,
                    source_url=source_url,
                    dl_doc=result.dl_doc,
                )

            return ToolResult(success=True, data=result.content)
        except Exception as e:
            logger.warning("Document conversion failed for %s: %s", source, e, exc_info=True)
            return ToolResult(success=False, data="", error=str(e))
```

**Step 3: Run tests**

Run: `pytest tests/test_ingester.py -v`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add odigos/providers/docling.py odigos/tools/document.py tests/test_ingester.py
git commit -m "feat: enhance DocTool to auto-ingest documents into vector memory"
```

---

### Task 3: Wire into main.py

**Files:**
- Modify: `odigos/main.py`

**Context:** `DocumentIngester` needs `db` and `vector_memory`. `DocTool` needs the `ingester` passed to its constructor. The wiring goes in the startup lifecycle where DocTool is already created.

**Step 1: Update main.py wiring**

In `odigos/main.py`, find the DocTool initialization block (after `docling_provider = DoclingProvider()`):

Replace:
```python
    doc_tool = DocTool(provider=docling_provider)
```

With:
```python
    from odigos.memory.ingester import DocumentIngester

    doc_ingester = DocumentIngester(db=_db, vector_memory=vector_memory)
    doc_tool = DocTool(provider=docling_provider, ingester=doc_ingester)
```

**Step 2: Run tests**

Run: `pytest tests/test_ingester.py -v`
Expected: ALL PASS

**Step 3: Commit**

```bash
git add odigos/main.py
git commit -m "feat: wire DocumentIngester into DocTool via main.py"
```
