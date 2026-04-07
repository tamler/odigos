# Memory Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Durable, rebuildable knowledge persistence — wiki files as the durable layer, DB as the operational index, with structured entity extraction, provenance tracking, and periodic lint maintenance.

**Architecture:** The reflector extracts entities/facts via a dedicated cheap LLM call (replacing fragile HTML comment parsing). DB remains primary for writes. A write-ahead queue (`pending_wiki_writes`) ensures the heartbeat's wiki projection phase catches all changes even after crashes. On empty DB startup with existing wiki files, a rebuild process reconstructs the operational tables.

**Tech Stack:** Python 3.12, aiosqlite, SQLite json_extract, sentence-transformers (existing), YAML frontmatter via simple string formatting

---

## File Structure

| File | Responsibility |
|------|---------------|
| `odigos/memory/extractor.py` | **New** — Structured entity/fact/relationship extraction via cheap LLM call |
| `odigos/memory/wiki_writer.py` | **New** — Writes entity pages, topic indexes, index.md, log.md, conversation summaries |
| `odigos/memory/wiki_reader.py` | **New** — Parses wiki files for DB rebuild on empty startup |
| `odigos/memory/source_archiver.py` | **New** — Saves cleaned markdown to data/sources/ with YAML frontmatter |
| `odigos/core/heartbeat/wiki_maintenance.py` | **New** — Heartbeat phase 3d: drain pending writes, wiki projection, graduation, lint |
| `odigos/core/reflector.py` | Remove HTML comment parsing, add extractor call, queue pending wiki writes |
| `odigos/memory/manager.py` | Update store() to accept extractor output instead of raw entity dicts |
| `odigos/memory/graph.py` | Add source_type/source_id to create_entity() and create_edge() |
| `odigos/core/heartbeat/orchestrator.py` | Add phase 3d wiki maintenance call |
| `odigos/db.py` | Add rebuild-from-wiki detection on empty DB |
| `odigos/tools/scrape.py` | Call source_archiver after scraping |
| `odigos/memory/ingester.py` | Call source_archiver for document ingestion |
| `schema.sql` | Add source_type, source_id, content_hash columns; add pending_wiki_writes table |
| `tests/test_extractor.py` | **New** — Tests for entity/fact extraction |
| `tests/test_wiki_writer.py` | **New** — Tests for wiki file generation |
| `tests/test_wiki_reader.py` | **New** — Tests for wiki file parsing and rebuild |
| `tests/test_source_archiver.py` | **New** — Tests for source archival |

---

### Task 1: Schema Updates

Add provenance columns and the write-ahead queue table.

**Files:**
- Modify: `schema.sql`

- [ ] **Step 1: Add provenance columns to entities table**

Add `source_type TEXT`, `source_id TEXT`, and `content_hash TEXT` columns after the existing `source` column in the `entities` CREATE TABLE statement in `schema.sql`.

- [ ] **Step 2: Add provenance columns to user_facts table**

Add `source_type TEXT`, `source_id TEXT`, and `content_hash TEXT` columns to the `user_facts` table.

- [ ] **Step 3: Add pending_wiki_writes table**

Add after the memory tables section in `schema.sql`:

```sql
CREATE TABLE IF NOT EXISTS pending_wiki_writes (
    id TEXT PRIMARY KEY,
    entity_id TEXT,
    fact_id TEXT,
    operation TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_pending_wiki_created ON pending_wiki_writes(created_at);
```

`operation` values: `entity_created`, `entity_updated`, `fact_created`, `fact_updated`, `fact_deleted`, `conversation_summary`.

- [ ] **Step 4: Verify schema**

Run: `sqlite3 :memory: < schema.sql 2>&1 | grep -v vec0`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add schema.sql
git commit -m "schema: add provenance columns and pending_wiki_writes table"
```

---

### Task 2: Entity/Fact Extractor

Create the structured extraction module that replaces inline HTML comment parsing.

**Files:**
- Create: `odigos/memory/extractor.py`
- Create: `tests/test_extractor.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_extractor.py` with 4 tests:
1. `test_extract_entities_and_facts` — provide a FakeLLM that returns valid JSON with entities, facts, relationships. Assert all three are extracted correctly.
2. `test_extract_returns_empty_on_small_talk` — user message "thanks" → skip extraction, return empty.
3. `test_extract_returns_empty_on_short_message` — user message "ok" (< 20 chars) → skip, return empty.
4. `test_extract_handles_malformed_response` — FakeLLM returns invalid JSON → return empty, no crash.

The `FakeLLM` class should have an async `complete(messages, **kwargs)` method returning a SimpleNamespace with `content`, `model`, `tokens_in`, `tokens_out`, `cost_usd`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_extractor.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement extractor**

Create `odigos/memory/extractor.py`:

```python
"""Structured entity/fact/relationship extraction from conversations.

Replaces the fragile <!--entities--> HTML comment pattern. Runs a single
cheap LLM call to extract structured knowledge from each conversation turn.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.providers.base import LLMProvider

logger = logging.getLogger(__name__)

_EMPTY = {"entities": [], "facts": [], "relationships": []}

_SMALL_TALK = re.compile(
    r"^(ok|okay|yes|no|yeah|nah|sure|thanks|thank you|cool|got it|"
    r"nice|great|awesome|perfect|good|fine|right|yep|nope|hm+|ah+|oh+)[\.\!\?]?$",
    re.IGNORECASE,
)

_MIN_MESSAGE_LENGTH = 20

_EXTRACTION_PROMPT = """\
Extract entities, facts, and relationships from this conversation turn.
Return JSON only, no explanation.

User: {user_message}
Assistant: {assistant_response}

Return this exact JSON structure (empty arrays if nothing to extract):
{{"entities": [{{"name": "...", "type": "person|tool|project|place|organization|concept", "summary": "..."}}],
 "facts": [{{"text": "...", "category": "preference|knowledge|goal|habit|general", "about": "entity name"}}],
 "relationships": [{{"from": "entity name", "relationship": "verb phrase", "to": "entity name"}}]}}"""


def content_hash(text: str) -> str:
    """SHA-256 hash of text for dedup."""
    return hashlib.sha256(text.strip().lower().encode()).hexdigest()[:16]


async def extract_knowledge(
    provider: LLMProvider,
    user_message: str,
    assistant_response: str,
    model: str = "",
) -> dict:
    """Extract entities, facts, and relationships from a conversation turn.

    Returns {"entities": [...], "facts": [...], "relationships": [...]}.
    Returns empty lists on small talk, short messages, or extraction failure.
    """
    # Relevance gate
    if len(user_message.strip()) < _MIN_MESSAGE_LENGTH:
        return _EMPTY
    if _SMALL_TALK.match(user_message.strip()):
        return _EMPTY

    prompt = _EXTRACTION_PROMPT.format(
        user_message=user_message[:500],
        assistant_response=assistant_response[:500],
    )

    try:
        response = await provider.complete(
            [{"role": "user", "content": prompt}],
            max_tokens=500,
            temperature=0.1,
            model=model or None,
        )
        raw = response.content.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = re.sub(r"^```\w*\n?", "", raw)
            raw = re.sub(r"\n?```\s*$", "", raw)
        parsed = json.loads(raw)
        return {
            "entities": parsed.get("entities", []),
            "facts": parsed.get("facts", []),
            "relationships": parsed.get("relationships", []),
        }
    except (json.JSONDecodeError, Exception) as e:
        logger.debug("Knowledge extraction failed: %s", e)
        return _EMPTY
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_extractor.py -v`
Expected: All 4 PASS

- [ ] **Step 5: Commit**

```bash
git add odigos/memory/extractor.py tests/test_extractor.py
git commit -m "feat: structured entity/fact extractor — replaces HTML comment parsing"
```

---

### Task 3: Source Archiver

Save cleaned markdown to `data/sources/` with YAML frontmatter.

**Files:**
- Create: `odigos/memory/source_archiver.py`
- Create: `tests/test_source_archiver.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_source_archiver.py` with 4 tests:
1. `test_archive_creates_file` — archive a URL + content, verify file exists at `data/sources/YYYY-MM-DD-title.md` with correct frontmatter and body.
2. `test_archive_dedup_by_hash` — archive same content twice, verify only one file created.
3. `test_archive_sanitizes_filename` — URL with special chars gets a clean slug.
4. `test_archive_returns_filepath` — verify the returned path matches where the file was written.

Use `tmp_path` fixture to avoid writing to real `data/sources/`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_source_archiver.py -v`
Expected: FAIL

- [ ] **Step 3: Implement source archiver**

Create `odigos/memory/source_archiver.py`:

```python
"""Archive external content as cleaned markdown in data/sources/.

Source files are immutable — the agent reads from them but never modifies them.
Each file has YAML frontmatter with url, title, scraped_at, content_type, sha256.
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_SOURCES_DIR = Path("data/sources")


def _slugify(text: str, max_len: int = 60) -> str:
    """Convert text to a filesystem-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:max_len]


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


async def archive_source(
    content: str,
    title: str,
    url: str | None = None,
    content_type: str = "article",
    sources_dir: Path | None = None,
) -> str | None:
    """Save cleaned markdown to data/sources/. Returns the file path or None if duplicate."""
    base = sources_dir or _SOURCES_DIR
    base.mkdir(parents=True, exist_ok=True)

    sha = _sha256(content)

    # Dedup: check if any existing file has the same hash
    for existing in base.glob("*.md"):
        try:
            header = existing.read_text(encoding="utf-8")[:500]
            if f"sha256: {sha}" in header:
                logger.debug("Source already archived: %s", existing.name)
                return None
        except Exception:
            continue

    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    slug = _slugify(title) if title else _slugify(url or "untitled")
    filename = f"{date}-{slug}.md"
    filepath = base / filename

    # Avoid collision
    counter = 1
    while filepath.exists():
        filepath = base / f"{date}-{slug}-{counter}.md"
        counter += 1

    frontmatter = f"---\nurl: {url or ''}\ntitle: {title}\nscraped_at: {datetime.now(timezone.utc).isoformat()}\ncontent_type: {content_type}\nsha256: {sha}\n---\n\n"
    filepath.write_text(frontmatter + content, encoding="utf-8")
    logger.info("Archived source: %s", filepath.name)
    return str(filepath)
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_source_archiver.py -v`
Expected: All 4 PASS

- [ ] **Step 5: Commit**

```bash
git add odigos/memory/source_archiver.py tests/test_source_archiver.py
git commit -m "feat: source archiver — save cleaned markdown to data/sources/"
```

---

### Task 4: Wiki Writer

Write entity pages, topic indexes, index.md, log.md, and conversation summaries.

**Files:**
- Create: `odigos/memory/wiki_writer.py`
- Create: `tests/test_wiki_writer.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_wiki_writer.py` with tests:
1. `test_write_entity_page` — write a graduated entity, verify file at `wiki/entities/name.md` with correct frontmatter (id, type, aliases, confidence, sources, updated_at) and body (facts, relationships with backlinks).
2. `test_write_topic_index` — write a topic index with graduated and ungraduated entities, verify correct format.
3. `test_write_index_md` — generate master index from a set of entities, verify links and summaries.
4. `test_append_log` — append an operation to log.md, verify parseable format.
5. `test_write_conversation_summary` — write a summary file to `wiki/conversations/`.
6. `test_entity_graduation` — entity with 3+ facts gets a full page, entity with 1 fact stays in topic index.

Use `tmp_path` fixture for the wiki directory.

- [ ] **Step 2: Run tests, verify they fail**

Run: `python3 -m pytest tests/test_wiki_writer.py -v`
Expected: FAIL

- [ ] **Step 3: Implement wiki writer**

Create `odigos/memory/wiki_writer.py`. Key class `WikiWriter` with:

```python
class WikiWriter:
    def __init__(self, wiki_dir: Path | None = None):
        self.wiki_dir = wiki_dir or Path("data/wiki")

    async def write_entity_page(self, entity: dict, facts: list[dict], relationships: list[dict]) -> str:
        """Write a full entity page to wiki/entities/{slug}.md. Returns filepath."""

    async def write_topic_index(self, entity_type: str, graduated: list[dict], indexed: list[dict]) -> str:
        """Write a topic index to wiki/topics/{type}.md. Returns filepath."""

    async def write_index(self, all_entities: list[dict], topic_types: list[str]) -> str:
        """Regenerate wiki/index.md from current state."""

    async def append_log(self, operation: str, details: str) -> None:
        """Append an entry to wiki/log.md."""

    async def write_conversation_summary(self, conv_id: str, title: str, summary: str, message_count: int, created_at: str, facts_extracted: list[str]) -> str:
        """Write a conversation summary to wiki/conversations/."""

    def should_graduate(self, fact_count: int, relationship_count: int) -> bool:
        """Entity graduates to full page at 3+ facts or 2+ relationships."""
        return fact_count >= 3 or relationship_count >= 2
```

Entity pages include a `## Backlinks` section showing entities that reference this entity (bidirectional relationships).

YAML frontmatter includes `id`, `type`, `aliases`, `confidence`, `sources`, `updated_at` — all parseable by the wiki reader for rebuild.

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_wiki_writer.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add odigos/memory/wiki_writer.py tests/test_wiki_writer.py
git commit -m "feat: wiki writer — entity pages, topic indexes, index, log, summaries"
```

---

### Task 5: Wiki Reader (Rebuild)

Parse wiki files to reconstruct DB tables on empty startup.

**Files:**
- Create: `odigos/memory/wiki_reader.py`
- Create: `tests/test_wiki_reader.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_wiki_reader.py` with tests:
1. `test_parse_entity_page` — create a wiki entity file, parse it, verify entity dict with id, type, name, aliases, confidence, sources.
2. `test_parse_topic_index` — create a topic index file, parse ungraduated entities from the Index section.
3. `test_parse_facts_with_sources` — parse fact lines with `[conv:id]` citations, extract text and source references.
4. `test_parse_relationships` — parse relationship lines like `**owns** -> [Odigos](odigos.md)`, extract from/relationship/to.
5. `test_rebuild_from_wiki` — create a mini wiki directory with entity pages and topic indexes. Call `rebuild_from_wiki(db, wiki_dir)` with a real in-memory SQLite DB. Verify entities, edges, and user_facts tables are populated.

- [ ] **Step 2: Run tests, verify they fail**

Run: `python3 -m pytest tests/test_wiki_reader.py -v`
Expected: FAIL

- [ ] **Step 3: Implement wiki reader**

Create `odigos/memory/wiki_reader.py`. Key functions:

```python
def parse_entity_page(filepath: Path) -> dict:
    """Parse a wiki entity page. Returns {id, type, name, aliases, confidence, sources, facts, relationships}."""

def parse_topic_index(filepath: Path) -> list[dict]:
    """Parse ungraduated entities from a topic index. Returns [{name, type, summary, sources}]."""

async def rebuild_from_wiki(db: Database, wiki_dir: Path) -> dict:
    """Rebuild DB tables from wiki files. Returns {entities: int, facts: int, edges: int, sources: int}."""
```

The YAML frontmatter parser reads between `---` delimiters. Facts are parsed from `## Facts` section lines matching `- text [source:id]`. Relationships from `## Relationships` lines matching `**verb** -> target`.

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_wiki_reader.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add odigos/memory/wiki_reader.py tests/test_wiki_reader.py
git commit -m "feat: wiki reader — parse wiki files for DB rebuild"
```

---

### Task 6: Graph Provenance

Add source_type and source_id to EntityGraph's create_entity() and create_edge().

**Files:**
- Modify: `odigos/memory/graph.py`

- [ ] **Step 1: Update create_entity()**

Add `source_type: str | None = None` and `source_id: str | None = None` parameters. Include them in the INSERT:

```python
async def create_entity(
    self,
    entity_type: str,
    name: str,
    properties: dict | None = None,
    confidence: float = 1.0,
    source: str | None = None,
    source_type: str | None = None,
    source_id: str | None = None,
) -> str:
```

Update the SQL to include `source_type, source_id` columns.

- [ ] **Step 2: Update create_edge()**

Add `source_type: str | None = None` and `source_id: str | None = None`. Store in `metadata_json` (edges don't have dedicated provenance columns — metadata is fine for edges).

- [ ] **Step 3: Run existing tests**

Run: `python3 -m pytest tests/ -q --ignore=tests/test_relevance.py 2>&1 | tail -10`
Expected: No regressions

- [ ] **Step 4: Commit**

```bash
git add odigos/memory/graph.py
git commit -m "feat: entity graph provenance — source_type/source_id on create"
```

---

### Task 7: Update Reflector

Remove HTML comment parsing, add extractor call, queue pending wiki writes.

**Files:**
- Modify: `odigos/core/reflector.py`

- [ ] **Step 1: Remove ENTITY_PATTERN and ENTITY_FALLBACK regex constants**

Delete the four regex patterns at module level (lines ~22-25): `ENTITY_PATTERN`, `ENTITY_FALLBACK`, `CORRECTION_PATTERN`, `CORRECTION_FALLBACK`.

Keep `CORRECTION_PATTERN` and `CORRECTION_FALLBACK` — corrections are still inline. Only entity extraction moves to the extractor.

- [ ] **Step 2: Remove entity parsing from reflect()**

In `reflect()`, remove the block that searches for `ENTITY_PATTERN`/`ENTITY_FALLBACK` in `response.content` and strips the HTML comment. The response content is now used as-is (no entity block to strip).

- [ ] **Step 3: Add extractor call**

After `bus.publish()` and before `memory_manager.store()`, add:

```python
        # Extract entities/facts via dedicated LLM call
        extracted = {"entities": [], "facts": [], "relationships": []}
        if user_message and len(user_message.strip()) >= 20:
            try:
                from odigos.memory.extractor import extract_knowledge
                extracted = await extract_knowledge(
                    provider=self._extraction_provider or self.db,  # cheap model
                    user_message=user_message,
                    assistant_response=content,
                    model=self._extraction_model or "",
                )
            except Exception:
                logger.warning("Knowledge extraction failed", exc_info=True)
```

The reflector needs an `extraction_provider` (cheap LLM) and `extraction_model` passed in `__init__`. Wire these from bootstrap.

- [ ] **Step 4: Pass extracted data to memory_manager.store()**

Change the `memory_manager.store()` call to pass the extractor output:

```python
        if self.memory_manager and user_message is not None:
            try:
                await self.memory_manager.store(
                    conversation_id=conversation_id,
                    user_message=user_message,
                    assistant_response=content,
                    extracted=extracted,
                )
            except Exception:
                logger.warning("Memory storage failed", exc_info=True)
```

- [ ] **Step 5: Queue pending wiki writes**

After storing entities/facts, insert into `pending_wiki_writes` for each entity and fact:

```python
        for entity in extracted.get("entities", []):
            await self.db.execute(
                "INSERT INTO pending_wiki_writes (id, entity_id, operation) VALUES (?, ?, ?)",
                (uuid.uuid4().hex, entity.get("_stored_id", ""), "entity_created"),
            )
        for fact in extracted.get("facts", []):
            await self.db.execute(
                "INSERT INTO pending_wiki_writes (id, fact_id, operation) VALUES (?, ?, ?)",
                (uuid.uuid4().hex, fact.get("_stored_id", ""), "fact_created"),
            )
```

The `_stored_id` is set by memory_manager.store() after the DB insert.

- [ ] **Step 6: Commit**

```bash
git add odigos/core/reflector.py
git commit -m "refactor: reflector uses extractor instead of HTML comment parsing"
```

---

### Task 8: Update Memory Manager

Update store() to accept extractor output and add provenance.

**Files:**
- Modify: `odigos/memory/manager.py`

- [ ] **Step 1: Update store() signature**

Change from accepting `extracted_entities: list[dict]` to `extracted: dict`:

```python
async def store(
    self,
    conversation_id: str,
    user_message: str,
    assistant_response: str,
    extracted: dict | None = None,
) -> None:
```

Where `extracted` has keys `entities`, `facts`, `relationships` from the extractor.

- [ ] **Step 2: Update _store_impl() entity handling**

Replace the old entity iteration (which called `self.resolver.resolve()` with name/type/context) with:

```python
        extracted = extracted or {"entities": [], "facts": [], "relationships": []}

        # Store entities with provenance
        for entity_data in extracted["entities"]:
            entity_id = await self.resolver.resolve(
                entity_data["name"],
                entity_data.get("type", "concept"),
                context=user_message,
                source_type="conversation",
                source_id=conversation_id,
            )
            entity_data["_stored_id"] = entity_id

        # Store relationships
        for rel in extracted["relationships"]:
            from_entities = await self.graph.find_entity(rel["from"])
            to_entities = await self.graph.find_entity(rel["to"])
            if from_entities and to_entities:
                await self.graph.create_edge(
                    from_entities[0]["id"], rel["relationship"], to_entities[0]["id"],
                    source_type="conversation", source_id=conversation_id,
                )

        # Store facts with provenance and SHA-256 dedup
        for fact_data in extracted["facts"]:
            fact_text = fact_data["text"]
            fact_hash = hashlib.sha256(fact_text.strip().lower().encode()).hexdigest()[:16]
            existing = await self.db.fetch_one(
                "SELECT id FROM user_facts WHERE content_hash = ?", (fact_hash,)
            ) if hasattr(self, 'db') else None
            if not existing:
                fact_id = uuid.uuid4().hex
                await self.db.execute(
                    "INSERT INTO user_facts (id, fact, category, source, source_type, source_id, content_hash, confidence, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
                    (fact_id, fact_text, fact_data.get("category", "general"), "extracted",
                     "conversation", conversation_id, fact_hash, 0.8),
                )
                fact_data["_stored_id"] = fact_id
```

Note: `_store_impl` needs access to `self.db`. The MemoryManager doesn't currently have a `db` reference. Add `db: Database` to `__init__` and pass it from bootstrap.

- [ ] **Step 3: Keep existing vector embedding of user messages**

The chunking + vector storage of user messages (existing phase 2 of `_store_impl`) stays unchanged.

- [ ] **Step 4: Commit**

```bash
git add odigos/memory/manager.py
git commit -m "refactor: memory manager accepts extractor output with provenance"
```

---

### Task 9: Wiki Maintenance Heartbeat Phase

Create the heartbeat phase that drains pending writes and projects wiki files.

**Files:**
- Create: `odigos/core/heartbeat/wiki_maintenance.py`
- Modify: `odigos/core/heartbeat/orchestrator.py`

- [ ] **Step 1: Create wiki_maintenance.py**

```python
"""Heartbeat phase 3d: Wiki maintenance — drain pending writes, project files, lint."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.core.heartbeat.orchestrator import Heartbeat

logger = logging.getLogger(__name__)


async def run_wiki_maintenance(hb: Heartbeat) -> bool:
    """Drain pending_wiki_writes queue and update wiki files. Returns True if work done."""
    if not hb.db:
        return False

    # Check for pending writes
    pending = await hb.db.fetch_all(
        "SELECT * FROM pending_wiki_writes ORDER BY created_at LIMIT 50"
    )
    if not pending:
        return False

    from odigos.memory.wiki_writer import WikiWriter
    writer = WikiWriter()
    did_work = False

    # Collect unique entity IDs that need page updates
    entity_ids = set()
    fact_ops = []
    summary_ops = []

    for row in pending:
        op = row["operation"]
        if op in ("entity_created", "entity_updated"):
            if row["entity_id"]:
                entity_ids.add(row["entity_id"])
        elif op in ("fact_created", "fact_updated", "fact_deleted"):
            fact_ops.append(row)
            # Facts may reference entities — find them
            if row["fact_id"]:
                fact = await hb.db.fetch_one("SELECT * FROM user_facts WHERE id = ?", (row["fact_id"],))
                if fact:
                    # Find entity by fact's "about" field if stored
                    pass  # Entity association handled by the entity_ids set
        elif op == "conversation_summary":
            summary_ops.append(row)

    # Update entity pages
    for entity_id in entity_ids:
        try:
            entity = await hb.db.fetch_one("SELECT * FROM entities WHERE id = ?", (entity_id,))
            if not entity:
                continue
            # Get facts about this entity
            facts = await hb.db.fetch_all(
                "SELECT * FROM user_facts WHERE fact LIKE ? ORDER BY confidence DESC LIMIT 20",
                (f"%{entity['name']}%",),
            )
            # Get relationships (both directions)
            edges_out = await hb.db.fetch_all(
                "SELECT e.*, t.name as target_name FROM edges e JOIN entities t ON e.target_id = t.id WHERE e.source_id = ?",
                (entity_id,),
            )
            edges_in = await hb.db.fetch_all(
                "SELECT e.*, s.name as source_name FROM edges e JOIN entities s ON e.source_id = s.id WHERE e.target_id = ?",
                (entity_id,),
            )

            all_rels = [{"from": entity["name"], "relationship": e["relationship"], "to": e["target_name"]} for e in edges_out]
            backlinks = [{"from": e["source_name"], "relationship": e["relationship"], "to": entity["name"]} for e in edges_in]

            fact_count = len(facts)
            rel_count = len(all_rels) + len(backlinks)

            if writer.should_graduate(fact_count, rel_count):
                await writer.write_entity_page(dict(entity), [dict(f) for f in facts], all_rels + backlinks)
            # Always update topic index for this entity type
            type_entities = await hb.db.fetch_all(
                "SELECT * FROM entities WHERE type = ? AND status = 'active' ORDER BY name",
                (entity["type"],),
            )
            graduated = []
            indexed = []
            for te in type_entities:
                te_facts = await hb.db.fetch_all(
                    "SELECT id FROM user_facts WHERE fact LIKE ? LIMIT 5",
                    (f"%{te['name']}%",),
                )
                te_edges = await hb.db.fetch_all(
                    "SELECT id FROM edges WHERE source_id = ? OR target_id = ? LIMIT 5",
                    (te["id"], te["id"]),
                )
                if writer.should_graduate(len(te_facts), len(te_edges)):
                    graduated.append(dict(te))
                else:
                    indexed.append(dict(te))
            await writer.write_topic_index(entity["type"], graduated, indexed)
            did_work = True
        except Exception:
            logger.exception("Wiki maintenance failed for entity %s", entity_id)

    # Rebuild index.md
    if did_work:
        all_entities = await hb.db.fetch_all("SELECT * FROM entities WHERE status = 'active' ORDER BY type, name")
        types = list(set(e["type"] for e in all_entities))
        await writer.write_index([dict(e) for e in all_entities], types)
        await writer.append_log("maintenance", f"Updated {len(entity_ids)} entities")

    # Clean processed rows
    for row in pending:
        await hb.db.execute("DELETE FROM pending_wiki_writes WHERE id = ?", (row["id"],))

    return did_work


async def run_wiki_lint(hb: Heartbeat) -> bool:
    """Lint pass — check for stale claims, orphans, contradictions. Runs every ~5 min."""
    if not hb.db:
        return False

    from odigos.memory.wiki_writer import WikiWriter
    writer = WikiWriter()
    findings = []

    # Orphan entities: no edges, created > 7 days ago
    orphans = await hb.db.fetch_all(
        "SELECT e.id, e.name, e.type FROM entities e "
        "WHERE e.status = 'active' "
        "AND e.id NOT IN (SELECT source_id FROM edges) "
        "AND e.id NOT IN (SELECT target_id FROM edges) "
        "AND e.created_at < datetime('now', '-7 days')"
    )
    for o in orphans:
        findings.append(f"Orphan entity: {o['name']} ({o['type']}) — no relationships, 7+ days old")

    if findings:
        await writer.append_log("lint", "\n".join(findings))

    return bool(findings)
```

- [ ] **Step 2: Add phase 3d to orchestrator**

In `odigos/core/heartbeat/orchestrator.py`, in the `_tick()` method, add after phase 3c (background.poll_pending_tasks):

```python
            # Phase 3d: Wiki maintenance
            from odigos.core.heartbeat import wiki_maintenance
            did_work |= await wiki_maintenance.run_wiki_maintenance(self)
```

And add a lint counter + call (every 10 ticks):

```python
            # Wiki lint (every 10 ticks)
            self._wiki_lint_counter = getattr(self, '_wiki_lint_counter', 0) + 1
            if self._wiki_lint_counter >= 10:
                self._wiki_lint_counter = 0
                await wiki_maintenance.run_wiki_lint(self)
```

- [ ] **Step 3: Commit**

```bash
git add odigos/core/heartbeat/wiki_maintenance.py odigos/core/heartbeat/orchestrator.py
git commit -m "feat: heartbeat phase 3d — wiki maintenance and lint"
```

---

### Task 10: Wire Source Archiver to Scrape and Ingest

Call source_archiver when scraping web pages or ingesting documents.

**Files:**
- Modify: `odigos/tools/scrape.py`
- Modify: `odigos/memory/ingester.py`

- [ ] **Step 1: Update scrape tool**

In `odigos/tools/scrape.py`, after the scrape returns content, archive it:

```python
        # Archive source content to data/sources/
        try:
            from odigos.memory.source_archiver import archive_source
            await archive_source(
                content=page.content,
                title=page.title or url,
                url=url,
                content_type="web_page",
            )
        except Exception:
            logger.debug("Source archival failed for %s", url)
```

Add this after the scrape succeeds but before returning the ToolResult.

- [ ] **Step 2: Update document ingester**

In `odigos/memory/ingester.py`, in the `ingest()` method, after storing in `documents` table, archive the source:

```python
        # Archive full content to data/sources/
        try:
            from odigos.memory.source_archiver import archive_source
            await archive_source(
                content=text,
                title=filename,
                url=source_url,
                content_type="document",
            )
        except Exception:
            logger.debug("Source archival failed for %s", filename)
```

- [ ] **Step 3: Commit**

```bash
git add odigos/tools/scrape.py odigos/memory/ingester.py
git commit -m "feat: archive sources on scrape and document ingest"
```

---

### Task 11: DB Rebuild Detection

On startup, if DB is empty but wiki files exist, trigger rebuild.

**Files:**
- Modify: `odigos/db.py`

- [ ] **Step 1: Add rebuild check after schema init**

In `odigos/db.py`, in `initialize()`, after `_ensure_schema()` and `run_migrations()`, add:

```python
        # Check if DB is empty but wiki files exist — trigger rebuild
        await self._maybe_rebuild_from_wiki()
```

Implement `_maybe_rebuild_from_wiki()`:

```python
    async def _maybe_rebuild_from_wiki(self) -> None:
        """If DB has no entities but data/wiki/ has files, rebuild from wiki."""
        from pathlib import Path
        wiki_dir = Path("data/wiki")
        if not wiki_dir.exists():
            return

        # Check if DB already has data
        row = await self.fetch_one("SELECT COUNT(*) as cnt FROM entities")
        if row and row["cnt"] > 0:
            return

        # Check if wiki has content
        entity_files = list(wiki_dir.glob("entities/*.md"))
        topic_files = list(wiki_dir.glob("topics/*.md"))
        if not entity_files and not topic_files:
            return

        logger.info("Empty DB with existing wiki files — rebuilding from wiki...")
        try:
            from odigos.memory.wiki_reader import rebuild_from_wiki
            stats = await rebuild_from_wiki(self, wiki_dir)
            logger.info("Wiki rebuild complete: %s", stats)
        except Exception:
            logger.exception("Wiki rebuild failed")
```

- [ ] **Step 2: Commit**

```bash
git add odigos/db.py
git commit -m "feat: auto-rebuild DB from wiki files on empty startup"
```

---

### Task 12: Wire Bootstrap + Integration Test

Wire the extractor provider to the reflector in bootstrap. Run full integration test.

**Files:**
- Modify: `odigos/bootstrap.py`

- [ ] **Step 1: Wire extraction provider to reflector**

In `bootstrap.py`, where the reflector's `message_bus` is wired, also set:

```python
        self.container.agent.reflector._extraction_provider = self.container.llm_provider
        self.container.agent.reflector._extraction_model = self.settings.llm.background_model or ""
```

- [ ] **Step 2: Wire db to memory_manager**

In `bootstrap.py`, where the memory_manager is created, ensure `db` is passed:

Find where `MemoryManager(...)` is constructed and add `db=db` parameter.

- [ ] **Step 3: Create data directories on startup**

In `bootstrap.py`, in `init_database()` or early startup, ensure:

```python
        from pathlib import Path
        Path("data/sources").mkdir(parents=True, exist_ok=True)
        Path("data/wiki/entities").mkdir(parents=True, exist_ok=True)
        Path("data/wiki/topics").mkdir(parents=True, exist_ok=True)
        Path("data/wiki/conversations").mkdir(parents=True, exist_ok=True)
        Path("data/wiki/synthesis").mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 4: Run full test suite**

Run: `python3 -m pytest tests/ -q --ignore=tests/test_relevance.py 2>&1 | tail -10`
Expected: All pass (pre-existing skips OK)

- [ ] **Step 5: Commit**

```bash
git add odigos/bootstrap.py
git commit -m "feat: wire extractor and wiki directories in bootstrap"
```

---

### Task 13: Deploy and Smoke Test

Deploy to Bob, verify the full flow.

- [ ] **Step 1: Push and deploy**

```bash
git push origin main
ssh root@82.25.91.86 "cd /opt/odigos && git fetch origin main && git reset --hard origin/main && chown -R odigos_agent:odigos_agent . && systemctl restart odigos"
```

- [ ] **Step 2: Send a message and verify extraction**

Send a message to Bob that mentions entities. Check the DB:

```bash
ssh root@82.25.91.86 "sqlite3 /opt/odigos/data/odigos.db 'SELECT name, type, source_type, source_id FROM entities ORDER BY created_at DESC LIMIT 5'"
```

- [ ] **Step 3: Verify wiki files generated**

Wait 30+ seconds for the heartbeat, then check:

```bash
ssh root@82.25.91.86 "ls -la /opt/odigos/data/wiki/topics/ && cat /opt/odigos/data/wiki/index.md"
```

- [ ] **Step 4: Verify source archival**

Tell Bob to look up a web page. Then check:

```bash
ssh root@82.25.91.86 "ls -la /opt/odigos/data/sources/"
```

- [ ] **Step 5: Test rebuild**

Stop Bob, delete the DB (keep wiki files), restart, verify rebuild:

```bash
ssh root@82.25.91.86 "systemctl stop odigos && rm -f /opt/odigos/data/odigos.db* && systemctl start odigos && sleep 10 && sqlite3 /opt/odigos/data/odigos.db 'SELECT COUNT(*) FROM entities'"
```

Expected: Entity count > 0 (rebuilt from wiki files).
