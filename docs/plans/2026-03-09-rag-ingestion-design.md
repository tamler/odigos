# RAG Document Ingestion Design

**Date:** 2026-03-09
**Status:** Approved

## Context

Odigos has a vector store (VectorMemory) used for conversation memory, entity names, and corrections. It also has a DocTool that converts PDF/DOCX/PPTX to text. But documents are read once and discarded -- the agent can't recall document content in future conversations. This is a foundational gap: the agent should be a knowledgeable assistant that remembers everything it reads.

## Decisions

1. **Always ingest** -- every document the agent reads is chunked, embedded, and stored in VectorMemory. No separate "read" vs "ingest" paths. Delete later if the user asks.
2. **Semantic chunking via Docling** -- split on document structure (headings, paragraphs, sections) rather than fixed-size windows. Better retrieval quality, already a dependency.
3. **Automatic retrieval** -- document chunks surface via the existing `memory_manager.recall()` pipeline. No new tool needed for retrieval. The agent just "knows" things from documents it's read.
4. **Enhance DocTool** -- the existing `read_document` tool gains ingestion as a side effect. One tool, always stores.
5. **Permanent until deleted** -- documents persist until the user asks to forget them. Future self-improvement loop can identify stale knowledge.
6. **File source agnostic** -- Telegram files are downloaded to disk, then treated as regular file paths. Same pipeline for all sources.

## Components

### 1. `documents` table (new migration)

```sql
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    source_url TEXT,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    ingested_at TEXT DEFAULT (datetime('now'))
);
```

Each chunk stored in VectorMemory references `source_id = document.id` with `source_type = "document_chunk"`.

### 2. DocumentIngester (`odigos/memory/ingester.py`)

Orchestrates: Docling semantic chunking -> embed each chunk via VectorMemory -> create document record.

```python
class DocumentIngester:
    def __init__(self, db, vector_memory, docling_provider):
        ...

    async def ingest(self, text: str, filename: str, source_url: str | None = None) -> str:
        # 1. Chunk text using Docling's semantic chunker
        # 2. Store each chunk in VectorMemory (source_type="document_chunk")
        # 3. Insert document record with chunk_count
        # Returns document_id
```

### 3. Enhanced DocTool

After extracting text (existing behavior), call `DocumentIngester.ingest()` to chunk and store. Return text to conversation as before so the agent can use it immediately AND recall it later.

### 4. Telegram file download

When a file is attached to a Telegram message, download it to a temp path via Telegram Bot API. Include the file path in the message to the agent. The agent processes it through DocTool like any other file.

### 5. Recall integration

No changes needed. `memory_manager.recall()` already searches all vectors. Document chunks have `source_type = "document_chunk"` and will surface alongside conversation memories and corrections. The only check: ensure `recall()` doesn't filter out this source type.

### 6. Document deletion

Agent can delete a document's chunks from VectorMemory and remove the document record when the user asks to forget it. Can be done through a simple method on DocumentIngester.

## Testing

- **TestDocumentIngester** -- mock chunker, verify chunks stored with correct source_type, verify document record created, verify chunk_count
- **TestDocToolIngestion** -- verify DocTool extracts AND ingests, returns text to conversation
- **TestRecallIncludesDocuments** -- verify document_chunk results surface in recall
- **TestDocumentDeletion** -- verify chunks and record removed
- **TestTelegramFileDownload** -- mock Telegram API, verify file downloaded to temp path
