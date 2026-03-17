# Document-Aware Code Sandbox Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the agent programmatic access to full document text via sandbox helpers (list_documents, read_document, search_documents), complementing RAG for deep document analysis.

**Architecture:** New `document_text` table stores full text at ingestion. CodeTool prepares a docs directory in the sandbox tmpdir before execution, injecting Python helper functions. Context assembly adds available documents to the system prompt.

**Tech Stack:** Python, SQLite, existing SandboxProvider (bubblewrap)

**Spec:** `docs/superpowers/specs/2026-03-17-document-query-design.md`

---

## Chunk 1: Storage and Ingestion

### Task 1: Migration and full text storage

**Files:**
- Create: `migrations/026_document_text.sql`
- Modify: `odigos/memory/ingester.py`
- Create: `tests/test_document_text.py`

- [ ] **Step 1: Create migration**

Create `migrations/026_document_text.sql`:
```sql
CREATE TABLE IF NOT EXISTS document_text (
    document_id TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    full_text TEXT NOT NULL
);
```

- [ ] **Step 2: Write tests**

Create `tests/test_document_text.py`:
```python
import pytest
from odigos.db import Database


@pytest.fixture
async def db(tmp_path):
    d = Database(str(tmp_path / "test.db"))
    await d.initialize()
    return d


@pytest.mark.asyncio
async def test_full_text_stored_on_ingest(db):
    """Ingesting a document stores full text in document_text table."""
    from odigos.memory.vectors import VectorMemory
    from odigos.memory.ingester import DocumentIngester

    vm = VectorMemory(db)
    ingester = DocumentIngester(db=db, vector_memory=vm)

    doc_id = await ingester.ingest(
        text="This is the full document text with many words and details.",
        filename="test.txt",
    )

    row = await db.fetch_one(
        "SELECT full_text FROM document_text WHERE document_id = ?",
        (doc_id,),
    )
    assert row is not None
    assert "full document text" in row["full_text"]


@pytest.mark.asyncio
async def test_full_text_deleted_on_cascade(db):
    """Deleting a document cascades to document_text."""
    from odigos.memory.vectors import VectorMemory
    from odigos.memory.ingester import DocumentIngester

    vm = VectorMemory(db)
    ingester = DocumentIngester(db=db, vector_memory=vm)

    doc_id = await ingester.ingest(text="Content here.", filename="del.txt")
    await ingester.delete(doc_id)

    row = await db.fetch_one(
        "SELECT full_text FROM document_text WHERE document_id = ?",
        (doc_id,),
    )
    assert row is None


@pytest.mark.asyncio
async def test_reingest_updates_full_text(db):
    """Re-ingesting with force=True replaces the full text."""
    from odigos.memory.vectors import VectorMemory
    from odigos.memory.ingester import DocumentIngester

    vm = VectorMemory(db)
    ingester = DocumentIngester(db=db, vector_memory=vm)

    await ingester.ingest(text="Original text.", filename="update.txt")
    doc_id = await ingester.ingest(
        text="Updated text.", filename="update.txt", force=True,
    )

    row = await db.fetch_one(
        "SELECT full_text FROM document_text WHERE document_id = ?",
        (doc_id,),
    )
    assert row is not None
    assert "Updated text" in row["full_text"]
```

- [ ] **Step 3: Store full text in ingester**

In `odigos/memory/ingester.py`, in the `ingest()` method, after the `INSERT INTO documents` statement and before the chunking loop, add:

```python
# Store full document text for code-based analysis
await self.db.execute(
    "INSERT OR REPLACE INTO document_text (document_id, full_text) VALUES (?, ?)",
    (doc_id, text),
)
```

Read the file first to find the exact insertion point (after the documents INSERT, before the chunking for loop).

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_document_text.py -xvs`
Expected: All 3 pass

- [ ] **Step 5: Commit**

```bash
git add migrations/026_document_text.sql odigos/memory/ingester.py tests/test_document_text.py
git commit -m "feat: store full document text for code-based analysis

New document_text table stores complete text at ingestion time.
Cascades on delete. Enables programmatic document access from sandbox."
```

---

## Chunk 2: CodeTool Document Preparation

### Task 2: Inject document helpers into CodeTool

**Files:**
- Modify: `odigos/tools/code.py`
- Create: `odigos/tools/doc_helpers.py`
- Create: `tests/test_doc_helpers.py`

- [ ] **Step 1: Create the helpers module**

Create `odigos/tools/doc_helpers.py`:

```python
"""Document helper preparation for the code sandbox."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Python code preamble injected into every sandbox execution when documents exist
DOC_PREAMBLE = '''
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
    safe_id = os.path.basename(doc["id"])
    path = os.path.join(_DOCS_DIR, f"{safe_id}.txt")
    if not os.path.exists(path):
        return f"Document text not loaded for \\'{doc[\\'name\\']}\\'. Re-upload the document to enable deep analysis."
    with open(path) as f:
        return f.read()

def search_documents(query, case_sensitive=False):
    """Search across all loaded documents for a text pattern. Returns matches with context."""
    results = []
    flags = 0 if case_sensitive else re.IGNORECASE
    pattern = re.compile(re.escape(query), flags)
    for filename in os.listdir(_DOCS_DIR):
        if not filename.endswith(".txt"):
            continue
        doc_id = filename[:-4]
        with open(os.path.join(_DOCS_DIR, filename)) as f:
            text = f.read()
        for match in pattern.finditer(text):
            start = max(0, match.start() - 200)
            end = min(len(text), match.end() + 200)
            results.append({"document": doc_id, "position": match.start(), "context": text[start:end]})
    return results
'''


async def prepare_doc_sandbox(db, tmpdir: str) -> bool:
    """Prepare document files in the sandbox temp directory.

    Creates {tmpdir}/docs/ with index.json and document text files.
    Returns True if documents were prepared, False if no documents exist.
    """
    # Check if any documents exist
    count_row = await db.fetch_one("SELECT COUNT(*) as count FROM documents")
    if not count_row or count_row["count"] == 0:
        return False

    docs_dir = Path(tmpdir) / "docs"
    docs_dir.mkdir(exist_ok=True)

    # Build index
    rows = await db.fetch_all(
        "SELECT d.id, d.filename, d.chunk_count, "
        "(CASE WHEN dt.document_id IS NOT NULL THEN 1 ELSE 0 END) as has_text "
        "FROM documents d "
        "LEFT JOIN document_text dt ON d.id = dt.document_id "
        "WHERE d.status = 'complete' "
        "ORDER BY d.filename"
    )

    index = []
    total_size = 0
    for row in rows:
        index.append({
            "id": row["id"],
            "name": row["filename"],
            "chunks": row["chunk_count"],
            "has_text": bool(row["has_text"]),
        })

    (docs_dir / "index.json").write_text(json.dumps(index, indent=2))

    # Calculate total text size to decide pre-loading strategy
    size_row = await db.fetch_one(
        "SELECT SUM(LENGTH(full_text)) as total_bytes FROM document_text"
    )
    total_size = size_row["total_bytes"] if size_row and size_row["total_bytes"] else 0

    # Pre-load documents: all if <1MB, otherwise load on demand
    if total_size < 1_000_000:
        # Small set: load everything
        text_rows = await db.fetch_all(
            "SELECT document_id, full_text FROM document_text"
        )
        for tr in text_rows:
            safe_id = os.path.basename(tr["document_id"])
            (docs_dir / f"{safe_id}.txt").write_text(tr["full_text"])
    else:
        logger.info("Large document set (%d bytes), loading on demand", total_size)

    return True
```

Note: The DOC_PREAMBLE string escaping for nested quotes needs care. Test this carefully. An alternative is to use triple-quoted strings with no internal quotes, or read the preamble from a separate .py file.

- [ ] **Step 2: Write tests for prepare_doc_sandbox**

Create `tests/test_doc_helpers.py`:
```python
import pytest
import json
from pathlib import Path
from odigos.db import Database
from odigos.tools.doc_helpers import prepare_doc_sandbox, DOC_PREAMBLE


@pytest.fixture
async def db_with_docs(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    await db.initialize()

    from odigos.memory.vectors import VectorMemory
    from odigos.memory.ingester import DocumentIngester

    vm = VectorMemory(db)
    ingester = DocumentIngester(db=db, vector_memory=vm)
    await ingester.ingest(text="Sherlock Holmes visited Trafalgar Square on a foggy morning.", filename="sherlock.txt")
    await ingester.ingest(text="Watson kept notes about Baker Street.", filename="watson.txt")
    return db


@pytest.mark.asyncio
async def test_prepare_creates_index(db_with_docs, tmp_path):
    sandbox_dir = tmp_path / "sandbox"
    sandbox_dir.mkdir()
    result = await prepare_doc_sandbox(db_with_docs, str(sandbox_dir))
    assert result is True
    index = json.loads((sandbox_dir / "docs" / "index.json").read_text())
    assert len(index) == 2
    names = [d["name"] for d in index]
    assert "sherlock.txt" in names
    assert "watson.txt" in names


@pytest.mark.asyncio
async def test_prepare_loads_small_docs(db_with_docs, tmp_path):
    sandbox_dir = tmp_path / "sandbox"
    sandbox_dir.mkdir()
    await prepare_doc_sandbox(db_with_docs, str(sandbox_dir))
    txt_files = list((sandbox_dir / "docs").glob("*.txt"))
    assert len(txt_files) == 2
    contents = [f.read_text() for f in txt_files]
    assert any("Trafalgar Square" in c for c in contents)


@pytest.mark.asyncio
async def test_prepare_no_docs(tmp_path):
    db = Database(str(tmp_path / "empty.db"))
    await db.initialize()
    sandbox_dir = tmp_path / "sandbox"
    sandbox_dir.mkdir()
    result = await prepare_doc_sandbox(db, str(sandbox_dir))
    assert result is False


def test_preamble_is_valid_python():
    """The injected preamble must be syntactically valid Python."""
    import ast
    ast.parse(DOC_PREAMBLE)
```

- [ ] **Step 3: Run tests**

Run: `.venv/bin/python -m pytest tests/test_doc_helpers.py -xvs`
Expected: All 4 pass

- [ ] **Step 4: Modify CodeTool to inject helpers**

In `odigos/tools/code.py`, modify the `CodeTool` class:

1. Add `db` parameter to `__init__`:
```python
def __init__(self, sandbox: SandboxProvider, db=None) -> None:
    self.sandbox = sandbox
    self._db = db
```

2. In `execute()`, before calling `self.sandbox.execute()`, prepare documents and prepend the preamble:
```python
async def execute(self, params: dict) -> ToolResult:
    code = params.get("code", "")
    if not code:
        return ToolResult(success=False, data="", error="No code provided")

    language = params.get("language", "python")

    # Prepare document helpers for Python execution
    if language == "python" and self._db:
        from odigos.tools.doc_helpers import prepare_doc_sandbox, DOC_PREAMBLE
        # We need access to the sandbox tmpdir -- but SandboxProvider creates it internally.
        # Solution: prepare docs inside the sandbox.execute call by modifying the code.
        has_docs = await self._has_documents()
        if has_docs:
            code = DOC_PREAMBLE + "\n" + code

    result = await self.sandbox.execute(code, language=language)
    ...rest unchanged...
```

Wait -- the sandbox creates the tmpdir internally in `execute()`. We need to prepare the doc files INSIDE that tmpdir BEFORE the subprocess runs. This means we need to modify `SandboxProvider.execute()` to accept a pre-execution callback, OR modify CodeTool to prepare docs differently.

**Better approach:** Pass a `prepare_callback` to `SandboxProvider.execute()` that runs after tmpdir creation but before subprocess execution. Or, modify SandboxProvider to accept a `files` dict that gets written to tmpdir.

**Simplest approach:** Add a `pre_files: dict[str, str]` parameter to `SandboxProvider.execute()` that writes files to tmpdir before running code. This is minimal and clean.

In `odigos/providers/sandbox.py`, modify `execute()`:
```python
async def execute(self, code: str, language: str = "python", pre_files: dict[str, str] | None = None) -> SandboxResult:
    with tempfile.TemporaryDirectory(...) as tmpdir:
        # Write pre-files to sandbox dir
        if pre_files:
            for rel_path, content in pre_files.items():
                file_path = Path(tmpdir) / rel_path
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(content)
        ...rest unchanged...
```

Then CodeTool uses `prepare_doc_sandbox()` to build the files dict and passes it:
```python
pre_files = {}
if language == "python" and self._db:
    pre_files = await self._prepare_doc_files()
    if pre_files:
        code = DOC_PREAMBLE + "\n" + code
result = await self.sandbox.execute(code, language=language, pre_files=pre_files)
```

Add `_prepare_doc_files()` to CodeTool that builds a dict of `{"docs/index.json": "...", "docs/{id}.txt": "..."}`.

Refactor `prepare_doc_sandbox()` in doc_helpers.py to return a `dict[str, str]` instead of writing to disk directly.

- [ ] **Step 5: Update main.py to pass db to CodeTool**

In `odigos/main.py`, find where `CodeTool(sandbox=sandbox_provider)` is constructed and add `db=_db`:
```python
CodeTool(sandbox=sandbox_provider, db=_db)
```

- [ ] **Step 6: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ --ignore=tests/e2e -x -q`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add odigos/tools/code.py odigos/tools/doc_helpers.py odigos/providers/sandbox.py tests/test_doc_helpers.py odigos/main.py
git commit -m "feat: inject document helpers into code sandbox

CodeTool prepares document files in sandbox tmpdir and injects
list_documents(), read_document(), search_documents() helpers.
SandboxProvider gains pre_files parameter for writing files to
tmpdir before execution."
```

---

## Chunk 3: Context Assembly and Capabilities

### Task 3: Add available documents to system prompt

**Files:**
- Modify: `odigos/core/context.py`

- [ ] **Step 1: Add document listing to context assembly**

In `odigos/core/context.py`, in the `build()` method, after the memory_context recall and before building the prompt, add a document listing:

```python
# Document listing for code-based analysis
doc_listing = ""
if self.db:
    doc_rows = await self.db.fetch_all(
        "SELECT d.id, d.filename, d.chunk_count "
        "FROM documents d WHERE d.status = 'complete' ORDER BY d.filename"
    )
    if doc_rows:
        lines = [
            "## Available documents",
            "Write Python code with these helpers to analyze documents in depth:",
            "list_documents(), read_document(name), search_documents(query)",
            "",
        ]
        for row in doc_rows:
            lines.append(f"- [{row['id'][:8]}] {row['filename']} ({row['chunk_count']} chunks)")
        doc_listing = "\n".join(lines)
```

Pass `doc_listing` into the system prompt assembly. Read the file to find exactly where `memory_context` is passed to `build_system_prompt()` and add `doc_listing` in a similar way.

The simplest approach: append `doc_listing` after memory_context in the parts list.

- [ ] **Step 2: Run tests**

Run: `.venv/bin/python -m pytest tests/test_core.py -x -q`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add odigos/core/context.py
git commit -m "feat: add available documents listing to system prompt

Agent sees document names and IDs in its context, enabling it
to decide when to use code for deeper document analysis."
```

### Task 4: Update capabilities prompt and deploy

**Files:**
- Modify: `data/agent/capabilities.md`

- [ ] **Step 1: Add document analysis guidance**

Add after the existing "Executable Skills" section:

```markdown
**Document Analysis:** When you need to search across documents, verify facts,
or cross-reference information, write Python code using the document helpers:
- list_documents() -- see all available documents with metadata
- read_document(name) -- read the full text of a specific document
- search_documents(query) -- search across all loaded documents for a text pattern
RAG gives you relevant chunks automatically. Use code when you need to dig deeper,
verify across multiple documents, or find specific passages.
```

- [ ] **Step 2: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ --ignore=tests/e2e -x -q`

- [ ] **Step 3: Build dashboard**

Run: `cd dashboard && npm run build`

- [ ] **Step 4: Commit and push**

```bash
git add -f data/agent/capabilities.md dashboard/dist/
git commit -m "feat: document analysis capabilities prompt and final build

Agent is guided to use code helpers for deep document analysis.
Completes the RLM-inspired document query feature."
git push
```

- [ ] **Step 5: Deploy to personal VPS**

```bash
ssh root@82.25.91.86 "export PATH=\$HOME/.local/bin:\$PATH && cd /opt/odigos && git pull && uv sync && systemctl restart odigos"
```

- [ ] **Step 6: Deploy to tester VPS**

```bash
ssh root@100.89.147.103 "cd /opt/odigos/repo && git pull && cd /opt/odigos && docker compose build --no-cache && docker compose up -d --force-recreate"
```
