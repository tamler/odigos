# File Upload Ingestion Pipeline — Design

**Goal:** Automatically ingest uploaded files into agent memory so content is immediately searchable and recallable, with provenance tracking back to the source file.

**Status:** The infrastructure exists (MarkItDown, DocumentIngester, hybrid search, `documents` table) but the upload endpoint doesn't trigger ingestion. This is a wiring job.

---

## Architecture

Upload (API or Telegram) -> Save original to disk -> Extract text via MarkItDown -> Deduplicate by filename -> Chunk via existing chunker -> Store in memory_entries + vectors -> Return extracted content to caller

### Core Principles

1. **Auto-ingest everything** — every uploaded file is parsed, chunked, and stored in active memory immediately
2. **Original preserved on disk** — raw files kept at `data/uploads/` as source of truth
3. **Provenance chain** — every memory chunk traces back to source document (filename, date, conversation)
4. **Deduplication by filename** — re-uploading same filename replaces old chunks, keeps latest version
5. **Agent prunes memory** — no warehouse tier; agent manages what to keep/forget over time

---

## Components

### 1. Upload Endpoint Changes (`odigos/api/upload.py`)

Current behavior: save file, return `{id, filename, size}`.

New behavior:
- Save file to disk (unchanged)
- Record in `documents` table with conversation_id if available
- Check for existing document with same filename — if found, purge old chunks
- Run MarkItDown extraction
- Chunk extracted text via DocumentIngester
- Return `{id, filename, size, chunk_count, content_preview}` where content_preview is the first ~2000 chars of extracted text

Ingestion runs inline (not background) since MarkItDown is fast for typical files. For very large files (>10MB), could be deferred, but YAGNI for now.

### 2. Telegram Integration (`odigos/channels/telegram.py`)

Current behavior: downloads file to `/tmp/odigos/`, passes path in message metadata, agent may or may not call `process_document`.

New behavior:
- After downloading, copy file to `data/uploads/` (persistent storage)
- Auto-ingest via same pipeline as API upload
- Include content preview in the message context so agent can respond immediately

### 3. Deduplication

When a file is uploaded with the same filename as an existing document:
- Delete old `memory_entries` where `source_id` = old document ID
- Delete corresponding vectors from `memory_vec`
- Update or replace the `documents` row
- Ingest new file's chunks
- Keep both physical files on disk (new one gets new file_id prefix)

### 4. Documents Table Enhancement

Current `documents` table has: `id, filename, source_url, chunk_count, ingested_at`.

Add:
- `conversation_id` — which conversation triggered the upload (nullable)
- `file_path` — path to original file on disk
- `file_size` — bytes
- `content_hash` — SHA-256 of file content (for exact-duplicate detection)
- `status` — `ingested`, `failed`, `processing`

### 5. Provenance in Recall

When the memory manager returns search results, include source document metadata:
- If `source_type = "document_chunk"`, look up the `documents` row via `source_id`
- Return `source_filename` and `ingested_at` alongside the memory content
- Agent can say "According to quarterly-report.pdf (uploaded March 14)..."

### 6. Content Preview in API Response

The upload endpoint returns extracted text (first ~2000 chars) so the calling conversation can immediately reference the content without needing a separate memory search. For the message-based API, the agent sees both the inline preview and has the full document in searchable memory.

---

## Data Flow

```
User uploads file
    |
    v
Save to data/uploads/{file_id}_{filename}
    |
    v
Hash file content (SHA-256)
    |
    v
Check documents table for same filename
    |
    +-- Found? Delete old memory_entries + vectors for that doc
    |
    v
Insert/update documents row (filename, path, hash, conversation_id, status=processing)
    |
    v
MarkItDown extracts text -> Markdown
    |
    v
Chunker splits into chunks (512 tokens, 64 overlap)
    |
    v
EmbeddingProvider generates vectors for each chunk
    |
    v
Store chunks in memory_entries (source_type=document_chunk, source_id=doc.id)
    |
    v
Update documents row (chunk_count, status=ingested)
    |
    v
Return {id, filename, size, chunk_count, content_preview}
```

---

## Error Handling

- MarkItDown fails to parse: set `status=failed`, return file metadata without content, log warning
- Partial chunk failure: store what succeeded, update chunk_count accordingly (ingester already handles this)
- File too large for inline extraction: still ingest to memory, just truncate the preview

---

## What We're NOT Building

- No warehouse/archive tier — agent prunes its own memory
- No background job queue — ingestion is synchronous and fast enough
- No file format restrictions beyond MarkItDown's capabilities
- No file versioning UI — just latest wins on same filename
- No separate file browsing API — files are accessed through memory search

---

## Files to Modify

| File | Change |
|------|--------|
| `migrations/023_document_upload.sql` | Add columns to documents table |
| `odigos/api/upload.py` | Wire ingestion pipeline into upload endpoint |
| `odigos/memory/ingester.py` | Add deduplication, provenance metadata |
| `odigos/channels/telegram.py` | Auto-ingest downloaded files |
| `odigos/memory/manager.py` | Include source document metadata in recall results |
