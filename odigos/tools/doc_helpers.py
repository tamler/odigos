"""Document helper functions injected into the code sandbox.

Provides list_documents(), read_document(), and search_documents()
for programmatic document analysis from sandboxed Python code.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.db import Database

logger = logging.getLogger(__name__)

DOC_PREAMBLE = r'''
import json, os, re

def list_documents():
    """Return a list of available documents with id, filename, and chunk_count."""
    index_path = os.path.join(os.getcwd(), "docs", "index.json")
    if not os.path.exists(index_path):
        return []
    with open(index_path) as f:
        return json.load(f)

def read_document(name_or_id):
    """Read a document by filename or id. Returns the full text or None."""
    docs = list_documents()
    doc_id = None
    for d in docs:
        if d["id"] == name_or_id or d["filename"] == name_or_id:
            doc_id = d["id"]
            break
    if doc_id is None:
        return None
    # Path traversal protection
    safe_name = os.path.basename(doc_id)
    doc_path = os.path.join(os.getcwd(), "docs", safe_name + ".txt")
    if not os.path.exists(doc_path):
        return None
    with open(doc_path) as f:
        return f.read()

def search_documents(query):
    """Regex search across all loaded documents. Returns list of {filename, matches}."""
    docs = list_documents()
    results = []
    pattern = re.compile(query, re.IGNORECASE)
    for d in docs:
        text = read_document(d["id"])
        if text is None:
            continue
        matches = []
        for i, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                matches.append({"line": i, "text": line.strip()})
        if matches:
            results.append({"filename": d["filename"], "id": d["id"], "matches": matches})
    return results

def analyze_text(text, question):
    """Request LLM analysis of a text passage.

    Prints an ANALYSIS_REQUEST marker that the agent will see in the code output
    and address in its next reasoning turn. This enables recursive LLM reasoning
    (RLM) from within sandboxed code without direct parent-process callbacks.
    """
    print(f"ANALYSIS_REQUEST: {question}")
    print(f"CONTEXT: {text[:2000]}")
    return "[Analysis will be provided by the agent]"
'''

_MAX_TOTAL_TEXT_BYTES = 1_000_000  # 1 MB


async def prepare_doc_files(db: Database) -> tuple[dict[str, str], bool]:
    """Build sandbox pre-files from ingested documents.

    Returns (files_dict, has_docs) where files_dict maps relative paths
    to file contents, and has_docs indicates whether any documents exist.
    """
    row = await db.fetch_one(
        "SELECT COUNT(*) as cnt FROM documents WHERE status = 'ingested'"
    )
    if not row or row["cnt"] == 0:
        return {}, False

    rows = await db.fetch_all(
        "SELECT d.id, d.filename, d.chunk_count "
        "FROM documents d WHERE d.status = 'ingested'"
    )
    if not rows:
        return {}, False

    # Build index.json
    index = [
        {"id": r["id"], "filename": r["filename"], "chunk_count": r["chunk_count"]}
        for r in rows
    ]

    files: dict[str, str] = {
        "docs/index.json": json.dumps(index, indent=2),
    }

    # Check total text size
    size_row = await db.fetch_one(
        "SELECT SUM(LENGTH(full_text)) as total FROM document_text"
    )
    total_size = size_row["total"] if size_row and size_row["total"] else 0

    if total_size < _MAX_TOTAL_TEXT_BYTES:
        # Load all document texts
        for r in rows:
            text_row = await db.fetch_one(
                "SELECT full_text FROM document_text WHERE document_id = ?",
                (r["id"],),
            )
            if text_row and text_row["full_text"]:
                files[f"docs/{r['id']}.txt"] = text_row["full_text"]

    return files, True
