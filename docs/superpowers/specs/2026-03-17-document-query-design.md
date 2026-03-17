# Document-Aware Code Sandbox Design

## Goal

Give the agent programmatic access to full document text via code execution, complementing RAG's chunk-based retrieval. RAG provides fast initial recall; the agent can write Python to search, filter, and cross-reference across documents when deeper analysis is needed. Inspired by the RLM paper (arxiv.org/html/2512.24601v2).

## Context

Current document retrieval uses RAG only: vector search + FTS5 + cross-encoder reranking returns the top N chunks. This works for simple factual lookups but fails when:
- The answer spans multiple chunks
- The answer requires cross-referencing across documents
- The relevant chunk wasn't ranked highly enough
- The question requires systematic scanning ("Did Sherlock ever visit Trafalgar Square?" across 60 stories)

The agent already has a code sandbox (SandboxProvider via CodeTool) and a multi-turn tool loop. We add document helper functions to the sandbox so the agent can write code against full document text when RAG alone isn't enough.

## Prerequisite: Store full document text

Currently `VectorMemory.store()` truncates content to 500 chars in `content_preview`. Full chunk text is not stored anywhere in the database. We need full text to reconstruct documents.

**New migration (026):** Add a `document_text` table for storing the complete original text per document:

```sql
CREATE TABLE IF NOT EXISTS document_text (
    document_id TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    full_text TEXT NOT NULL
);
```

**Modified ingestion:** `DocumentIngester.ingest()` stores the original `text` parameter (the full extracted text) into `document_text` alongside the existing chunking flow. This is the complete document text before chunking -- not a concatenation of chunks.

For existing documents: they won't have entries in `document_text`. The helper functions handle this gracefully (return "Document text not available -- re-upload to enable deep analysis").

## Architecture

No new tools. Four changes to existing infrastructure:

### 1. Document context in system prompt

After RAG results are injected into the prompt, add a section listing available documents:

```
## Available documents
You can access these documents programmatically via code execution.
Use the helper functions: list_documents(), read_document(name), search_documents(query)

- [doc-abc123] sherlock-hound.pdf (142 chunks)
- [doc-def456] sherlock-study-scarlet.pdf (98 chunks)
- [doc-ghi789] meeting-notes-march.pdf (12 chunks)
```

Metadata only -- names, IDs, chunk counts. Scales to hundreds of documents with minimal token cost.

### 2. Sandbox document helpers

Before each CodeTool execution, prepare document data in the sandbox's temp directory and inject helper functions.

**Sandbox path:** The SandboxProvider creates a temp directory (`tmpdir`) which is bind-mounted as `/sandbox` inside bubblewrap. Host `/tmp` is shadowed by a private tmpfs. Document files must be written to `tmpdir` (host side) so they appear at `/sandbox/docs/` inside the sandbox.

**Preparation (parent process, before sandbox execution):**
- Create `{tmpdir}/docs/` directory
- Write `index.json` with document metadata (id, filename, chunk_count)
- For documents referenced in RAG results for the current conversation, read full text from `document_text` table and write to `{tmpdir}/docs/{doc_id}.txt`
- Optimization: if total document text is under 1MB, pre-load all documents

**Helper functions (injected as Python code preamble):**

```python
import json, os, re

_DOCS_DIR = "/sandbox/docs"

def list_documents():
    """List all available documents with metadata."""
    _path = os.path.join(_DOCS_DIR, "index.json")
    if not os.path.exists(_path):
        return []
    with open(_path) as f:
        return json.load(f)

def read_document(name_or_id):
    """Read the full text of a document by name or ID."""
    index = list_documents()
    doc = None
    for d in index:
        if d["id"] == name_or_id or d["name"] == name_or_id:
            doc = d
            break
    if not doc:
        return f"Document not found: {name_or_id}"
    safe_id = os.path.basename(doc["id"])  # prevent path traversal
    path = os.path.join(_DOCS_DIR, f"{safe_id}.txt")
    if not os.path.exists(path):
        return f"Document text not loaded for '{doc['name']}'. Re-upload the document to enable deep analysis."
    with open(path) as f:
        return f.read()

def search_documents(query, case_sensitive=False):
    """Search across all loaded documents for a text pattern. Returns matches with surrounding context."""
    results = []
    flags = 0 if case_sensitive else re.IGNORECASE
    pattern = re.compile(re.escape(query), flags)
    for filename in os.listdir(_DOCS_DIR):
        if not filename.endswith(".txt"):
            continue
        doc_id = filename[:-4]  # strip .txt
        with open(os.path.join(_DOCS_DIR, filename)) as f:
            text = f.read()
        for match in pattern.finditer(text):
            start = max(0, match.start() - 200)
            end = min(len(text), match.end() + 200)
            results.append({
                "document": doc_id,
                "position": match.start(),
                "context": text[start:end],
            })
    return results
```

Pure Python, stdlib only, path traversal protected.

### 3. Document preparation in CodeTool

Modify `CodeTool.execute()` to prepare documents before running user code:

1. Check if any documents exist (`SELECT COUNT(*) FROM documents`)
2. If yes, create `{tmpdir}/docs/` and write `index.json`
3. Determine which documents to pre-load:
   - If total text < 1MB: load all from `document_text` table
   - Otherwise: load only documents whose IDs appear in the current conversation's RAG results
4. Write each document's full text to `{tmpdir}/docs/{doc_id}.txt`
5. Prepend the helper functions to the user's code string
6. Temp directory is cleaned up automatically by SandboxProvider

**RAG result linkage:** CodeTool needs to know which document IDs were referenced in RAG. Two options:
- (a) Pass RAG source IDs to CodeTool via the executor (add a `doc_context` field to the tool call context)
- (b) CodeTool queries the database for all documents and pre-loads based on size threshold

Option (b) is simpler and sufficient. For small sets, all docs are loaded anyway. For large sets, the agent can request specific documents via `read_document()` in a follow-up CodeTool call.

**Lazy loading protocol:** When `read_document()` returns "text not loaded", the agent understands it needs another CodeTool call. The agent's tool loop handles this naturally -- it reads the output, decides to load a specific document, and its next code execution will have it available (because CodeTool pre-loads based on what the agent asked for in previous output). To enable this:
- After each CodeTool execution, scan the output for `"Document text not loaded"` messages
- Extract the document name/ID from the message
- On the next CodeTool call, pre-load those documents in addition to the defaults

### 4. Capabilities prompt update

Add to `data/agent/capabilities.md`:

```
**Document Analysis:** When you need to search across documents, verify facts,
or cross-reference information, write Python code using the document helpers:
- list_documents() -- see all available documents with metadata
- read_document(name) -- read the full text of a specific document
- search_documents(query) -- search across all loaded documents for a text pattern
RAG gives you relevant chunks automatically. Use code when you need to dig deeper,
verify across multiple documents, or find specific passages. Note: search_documents()
only searches documents whose text has been loaded -- use list_documents() to check
what's available.
```

## What stays the same

- RAG retrieval (vector + FTS5 + reranker) -- unchanged, still runs on every message
- Document ingestion and chunking -- unchanged (plus full text storage)
- CodeTool interface -- unchanged (agent calls it the same way)
- SandboxProvider -- unchanged (still runs bubblewrap)

## Performance

- **Index preparation:** ~1ms (database query for document list)
- **Document loading:** ~5-10ms per document (read from document_text, write to temp file)
- **Small set (<1MB total):** all docs pre-loaded, ~50ms total
- **Large set (>1MB):** only relevant docs loaded, ~50ms for 5 docs
- **Helper execution:** pure Python file I/O, negligible
- **Temp cleanup:** automatic (SandboxProvider handles it)
- **Sandbox timeout:** consider 15s for document-heavy queries (vs 5s default)

## Files Modified

| File | Change |
|---|---|
| `migrations/026_document_text.sql` | New: document_text table |
| `odigos/memory/ingester.py` | Store full text in document_text table during ingestion |
| `odigos/tools/code.py` | Prepare doc temp dir, inject helpers, lazy load protocol |
| `odigos/core/context.py` | Add "Available documents" section to system prompt |
| `data/agent/capabilities.md` | Add document analysis guidance |
| `tests/test_document_query.py` | New: test helper functions and doc preparation |

## Security

- Document files written to sandbox tmpdir (bind-mounted as `/sandbox/docs/`)
- Path traversal prevented via `os.path.basename()` in `read_document()`
- Helper functions use only stdlib (json, os, re)
- Temp directory cleaned up after each execution
- Sandbox bubblewrap isolation unchanged
- Documents are the user's own uploaded files

## Out of Scope

- `query_llm()` inside sandbox (agent's tool loop handles recursion)
- Streaming results from long document scans
- Document caching across conversations (fresh temp dir per call)
- Automatic detection of when to use code vs RAG (agent decides)
- Word count per document (use chunk_count as proxy)
