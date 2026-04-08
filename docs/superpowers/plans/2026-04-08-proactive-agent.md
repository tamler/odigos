# Proactive Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the agent proactively helpful — replace idle_think with a structured scan→prioritize→execute→publish pipeline, unify all notifications into one persistent system, rename wiki→brain throughout, and add agent diary for self-continuity.

**Architecture:** A 4-stage proactive pipeline runs in the heartbeat when idle. Stage 1-2 (scan+prioritize) are synchronous in the tick. Stage 3-4 (execute+publish) run as an async background task. All artifacts go through BrainWriter. All notifications go through the upgraded Notifier with persistence and feedback tracking.

**Tech Stack:** Python 3.12, aiosqlite, asyncio, existing headless agent pipeline

---

## File Structure

| File | Responsibility |
|------|---------------|
| `odigos/memory/brain_writer.py` | **Renamed** from wiki_writer.py. Add write_synthesis(), write_source(), append_diary() |
| `odigos/memory/brain_reader.py` | **Renamed** from wiki_reader.py |
| `odigos/core/heartbeat/brain_maintenance.py` | **Renamed** from wiki_maintenance.py |
| `odigos/core/heartbeat/proactive.py` | **New** — 4-stage pipeline replacing idle_think |
| `odigos/api/notifications.py` | **New** — GET/PATCH notification endpoints |
| `odigos/core/notifier.py` | Upgrade: persist to notifications table, return ID, accept type/source |
| `odigos/core/heartbeat/orchestrator.py` | Replace idle_think with proactive, update brain_maintenance refs |
| `odigos/core/heartbeat/idle.py` | **Removed** — replaced by proactive.py |
| `odigos/memory/source_archiver.py` | **Removed** — absorbed into BrainWriter.write_source() |
| `odigos/core/reflector.py` | Update table name: pending_wiki_writes → pending_brain_writes |
| `odigos/db.py` | Update rebuild path: data/wiki → data/brain |
| `odigos/bootstrap.py` | Update directory paths, add proactive config |
| `odigos/config.py` | Add ProactiveConfig section |
| `odigos/api/callbacks.py` | Switch to unified Notifier.notify(type="status") |
| `odigos/core/heartbeat/background.py` | Switch to unified Notifier.notify(type="status") |
| `odigos/tools/scrape.py` | Switch source_archiver → BrainWriter.write_source() |
| `odigos/memory/ingester.py` | Switch source_archiver → BrainWriter.write_source() |
| `schema.sql` | Rename pending_wiki_writes → pending_brain_writes, add notifications table |
| `tests/test_brain_writer.py` | **Renamed** from test_wiki_writer.py |
| `tests/test_brain_reader.py` | **Renamed** from test_wiki_reader.py |
| `tests/test_proactive.py` | **New** — tests for the proactive pipeline |
| `tests/test_notifications.py` | **New** — tests for notification persistence |

---

### Task 1: Schema Updates

Add notifications table and rename pending_wiki_writes.

**Files:**
- Modify: `schema.sql`

- [ ] **Step 1: Rename pending_wiki_writes to pending_brain_writes**

Find the `pending_wiki_writes` table (around line 155) and rename:

```sql
CREATE TABLE IF NOT EXISTS pending_brain_writes (
    id TEXT PRIMARY KEY,
    entity_id TEXT,
    fact_id TEXT,
    operation TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_pending_brain_created ON pending_brain_writes(created_at);
```

Remove the old `pending_wiki_writes` and `idx_pending_wiki_created`.

- [ ] **Step 2: Add notifications table**

Add after the pending_brain_writes table:

```sql
CREATE TABLE IF NOT EXISTS notifications (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT,
    artifact_path TEXT,
    conversation_id TEXT,
    source TEXT,
    read INTEGER DEFAULT 0,
    reaction TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_notifications_created ON notifications(created_at);
CREATE INDEX IF NOT EXISTS idx_notifications_read ON notifications(read);
```

- [ ] **Step 3: Verify schema**

Run: `sqlite3 :memory: < schema.sql 2>&1 | grep -v vec0`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add schema.sql
git commit -m "schema: rename pending_wiki_writes → pending_brain_writes, add notifications table"
```

---

### Task 2: Rename WikiWriter → BrainWriter

Rename the file, class, and all references. Add the new methods.

**Files:**
- Rename: `odigos/memory/wiki_writer.py` → `odigos/memory/brain_writer.py`
- Rename: `tests/test_wiki_writer.py` → `tests/test_brain_writer.py`

- [ ] **Step 1: Rename files**

```bash
git mv odigos/memory/wiki_writer.py odigos/memory/brain_writer.py
git mv tests/test_wiki_writer.py tests/test_brain_writer.py
```

- [ ] **Step 2: Rename class WikiWriter → BrainWriter in brain_writer.py**

In `odigos/memory/brain_writer.py`:
- Rename `class WikiWriter` to `class BrainWriter`
- Change default `wiki_dir` to `brain_dir`: `self.brain_dir = brain_dir or Path("data/brain")`
- Replace all `self.wiki_dir` with `self.brain_dir`
- Update all log messages from "wiki" to "brain"

- [ ] **Step 3: Add write_synthesis() method**

```python
    async def write_synthesis(self, title: str, content: str, source: str,
                               source_context: str, conversation_id: str | None = None) -> str:
        """Write a proactive finding/suggestion to brain/synthesis/. Returns filepath."""
        synth_dir = self.brain_dir / "synthesis"
        synth_dir.mkdir(parents=True, exist_ok=True)

        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        slug = self._slugify(title)
        filepath = synth_dir / f"{date}-{slug}.md"
        counter = 1
        while filepath.exists():
            filepath = synth_dir / f"{date}-{slug}-{counter}.md"
            counter += 1

        now = datetime.now(timezone.utc).isoformat()
        fm = f"---\ntype: finding\ntitle: {title}\nsource: {source}\nsource_context: {source_context}\n"
        if conversation_id:
            fm += f"conversation_id: {conversation_id}\n"
        fm += f"created_at: {now}\n---\n\n"

        filepath.write_text(fm + f"# {title}\n\n{content}\n", encoding="utf-8")
        logger.info("Wrote synthesis: %s", filepath.name)
        return str(filepath)
```

- [ ] **Step 4: Add write_source() method (absorb source_archiver)**

```python
    async def write_source(self, content: str, title: str, url: str | None = None,
                            content_type: str = "article") -> str | None:
        """Write external content to data/sources/. Returns filepath or None if duplicate."""
        import hashlib
        sources_dir = Path("data/sources")
        sources_dir.mkdir(parents=True, exist_ok=True)

        sha = hashlib.sha256(content.encode()).hexdigest()

        # Dedup by SHA-256
        for existing in sources_dir.glob("*.md"):
            try:
                header = existing.read_text(encoding="utf-8")[:500]
                if f"sha256: {sha}" in header:
                    return None
            except Exception:
                continue

        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        slug = self._slugify(title) if title else self._slugify(url or "untitled")
        filepath = sources_dir / f"{date}-{slug}.md"
        counter = 1
        while filepath.exists():
            filepath = sources_dir / f"{date}-{slug}-{counter}.md"
            counter += 1

        now = datetime.now(timezone.utc).isoformat()
        fm = f"---\nurl: {url or ''}\ntitle: {title}\nscraped_at: {now}\ncontent_type: {content_type}\nsha256: {sha}\n---\n\n"
        filepath.write_text(fm + content, encoding="utf-8")
        logger.info("Archived source: %s", filepath.name)
        return str(filepath)
```

- [ ] **Step 5: Add append_diary() method**

```python
    async def append_diary(self, summary: str, open_threads: str = "") -> None:
        """Append an entry to data/agent/diary.md."""
        diary_dir = Path("data/agent")
        diary_dir.mkdir(parents=True, exist_ok=True)
        diary_path = diary_dir / "diary.md"

        now = datetime.now(timezone.utc).isoformat()
        entry = f"\n## [{now}] proactive_cycle\n{summary}\n"
        if open_threads:
            entry += f"Open threads: {open_threads}\n"

        with open(diary_path, "a", encoding="utf-8") as f:
            f.write(entry)
```

- [ ] **Step 6: Update test file imports**

In `tests/test_brain_writer.py`:
- Change `from odigos.memory.wiki_writer import WikiWriter` to `from odigos.memory.brain_writer import BrainWriter`
- Replace all `WikiWriter(` with `BrainWriter(`

- [ ] **Step 7: Run tests**

Run: `python3 -m pytest tests/test_brain_writer.py -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add odigos/memory/brain_writer.py tests/test_brain_writer.py
git rm odigos/memory/source_archiver.py
git commit -m "feat: WikiWriter → BrainWriter, add write_synthesis/write_source/append_diary"
```

---

### Task 3: Rename WikiReader → BrainReader + Update DB

Rename the reader and update the db.py rebuild path.

**Files:**
- Rename: `odigos/memory/wiki_reader.py` → `odigos/memory/brain_reader.py`
- Rename: `tests/test_wiki_reader.py` → `tests/test_brain_reader.py`
- Modify: `odigos/db.py`

- [ ] **Step 1: Rename files**

```bash
git mv odigos/memory/wiki_reader.py odigos/memory/brain_reader.py
git mv tests/test_wiki_reader.py tests/test_brain_reader.py
```

- [ ] **Step 2: Update brain_reader.py**

Rename the `rebuild_from_wiki` function to `rebuild_from_brain`. Update the `wiki_dir` parameter to `brain_dir`. Update all `data/wiki` path references to `data/brain`.

- [ ] **Step 3: Update test imports**

In `tests/test_brain_reader.py`, change all `wiki_reader` imports to `brain_reader`, `rebuild_from_wiki` to `rebuild_from_brain`.

- [ ] **Step 4: Update db.py**

In `odigos/db.py`, rename `_maybe_rebuild_from_wiki` to `_maybe_rebuild_from_brain`. Update the import from `odigos.memory.brain_reader import rebuild_from_brain`. Change `Path("data/wiki")` to `Path("data/brain")`.

- [ ] **Step 5: Run tests**

Run: `python3 -m pytest tests/test_brain_reader.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add odigos/memory/brain_reader.py tests/test_brain_reader.py odigos/db.py
git commit -m "feat: WikiReader → BrainReader, update rebuild path"
```

---

### Task 4: Rename wiki_maintenance → brain_maintenance

Rename the heartbeat module and update all references.

**Files:**
- Rename: `odigos/core/heartbeat/wiki_maintenance.py` → `odigos/core/heartbeat/brain_maintenance.py`
- Modify: `odigos/core/heartbeat/orchestrator.py`

- [ ] **Step 1: Rename file**

```bash
git mv odigos/core/heartbeat/wiki_maintenance.py odigos/core/heartbeat/brain_maintenance.py
```

- [ ] **Step 2: Update brain_maintenance.py**

- Rename `run_wiki_maintenance` to `run_brain_maintenance`
- Rename `run_wiki_lint` to `run_brain_lint`
- Change `from odigos.memory.wiki_writer import WikiWriter` to `from odigos.memory.brain_writer import BrainWriter`
- Replace all `WikiWriter()` with `BrainWriter()`
- Update table references: `pending_wiki_writes` → `pending_brain_writes`
- Update log messages: "wiki" → "brain"

- [ ] **Step 3: Update orchestrator.py**

- Change `from odigos.core.heartbeat import wiki_maintenance` to `from odigos.core.heartbeat import brain_maintenance`
- Change `wiki_maintenance.run_wiki_maintenance` to `brain_maintenance.run_brain_maintenance`
- Change `wiki_maintenance.run_wiki_lint` to `brain_maintenance.run_brain_lint`
- Rename `_wiki_lint_counter` to `_brain_lint_counter`

- [ ] **Step 4: Update reflector.py**

Change `INSERT INTO pending_wiki_writes` to `INSERT INTO pending_brain_writes` (two occurrences around lines 140, 147).

- [ ] **Step 5: Update bootstrap.py**

Change `Path("data/wiki/...")` to `Path("data/brain/...")` for all directory creation (lines 41-46).

- [ ] **Step 6: Run tests**

Run: `python3 -m pytest tests/ -q --ignore=tests/test_relevance.py 2>&1 | tail -10`
Expected: No regressions from rename

- [ ] **Step 7: Commit**

```bash
git add odigos/core/heartbeat/brain_maintenance.py odigos/core/heartbeat/orchestrator.py odigos/core/reflector.py odigos/bootstrap.py
git commit -m "feat: wiki_maintenance → brain_maintenance, update all wiki → brain refs"
```

---

### Task 5: Remove source_archiver + Update Callers

Remove the standalone module and switch callers to BrainWriter.write_source().

**Files:**
- Remove: `odigos/memory/source_archiver.py`
- Remove: `tests/test_source_archiver.py`
- Modify: `odigos/tools/scrape.py`
- Modify: `odigos/memory/ingester.py`

- [ ] **Step 1: Update scrape.py**

Replace:
```python
from odigos.memory.source_archiver import archive_source
await archive_source(content=..., title=..., url=..., content_type="web_page")
```
With:
```python
from odigos.memory.brain_writer import BrainWriter
await BrainWriter().write_source(content=..., title=..., url=..., content_type="web_page")
```

- [ ] **Step 2: Update ingester.py**

Same pattern — replace `archive_source` import with `BrainWriter().write_source()`.

- [ ] **Step 3: Remove old files**

```bash
git rm odigos/memory/source_archiver.py tests/test_source_archiver.py
```

- [ ] **Step 4: Commit**

```bash
git add odigos/tools/scrape.py odigos/memory/ingester.py
git commit -m "refactor: remove source_archiver, callers use BrainWriter.write_source()"
```

---

### Task 6: Upgrade Notifier + Notification API

Persist notifications to DB, add type/source params, create API endpoints.

**Files:**
- Modify: `odigos/core/notifier.py`
- Create: `odigos/api/notifications.py`
- Create: `tests/test_notifications.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_notifications.py`:

1. `test_notify_persists_to_db` — call notify(), verify row in notifications table with correct type, title, body, source.
2. `test_notify_returns_id` — verify notify() returns a notification UUID.
3. `test_list_notifications` — insert 3 notifications, GET /api/notifications, verify 3 returned ordered by created_at DESC.
4. `test_update_notification_reaction` — PATCH /api/notifications/{id} with `{reaction: "thumbs_up"}`, verify updated.
5. `test_unread_filter` — insert 2 read + 1 unread, GET /api/notifications?unread_only=true, verify 1 returned.

- [ ] **Step 2: Upgrade Notifier**

In `odigos/core/notifier.py`, update the `notify()` signature:

```python
async def notify(
    self,
    title: str,
    body: str,
    *,
    type: str = "status",
    artifact_path: str | None = None,
    conversation_id: str | None = None,
    source: str | None = None,
    channels: list[str] | None = None,
) -> str:
    """Persist notification + push to all channels. Returns notification ID."""
    import uuid
    notif_id = uuid.uuid4().hex

    # 1. Persist to DB
    if self.db:
        await self.db.execute(
            "INSERT INTO notifications (id, type, title, body, artifact_path, "
            "conversation_id, source) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (notif_id, type, title, body, artifact_path, conversation_id, source),
        )

    # 2. Push to channels (existing logic)
    # ... existing channel push code ...

    # 3. Web push (existing logic)
    await self._send_push_notifications(title, body)

    return notif_id
```

- [ ] **Step 3: Create notifications API**

Create `odigos/api/notifications.py`:

```python
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from odigos.api.deps import get_db, require_auth
from odigos.db import Database

router = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])

@router.get("/notifications")
async def list_notifications(
    limit: int = Query(default=20, ge=1, le=100),
    unread_only: bool = Query(default=False),
    db: Database = Depends(get_db),
):
    where = "WHERE read = 0" if unread_only else ""
    rows = await db.fetch_all(
        f"SELECT * FROM notifications {where} ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )
    return {"notifications": rows}

class NotificationUpdate(BaseModel):
    read: bool | None = None
    reaction: str | None = None

@router.patch("/notifications/{notification_id}")
async def update_notification(
    notification_id: str,
    update: NotificationUpdate,
    db: Database = Depends(get_db),
):
    sets = []
    params = []
    if update.read is not None:
        sets.append("read = ?")
        params.append(1 if update.read else 0)
    if update.reaction is not None:
        sets.append("reaction = ?")
        params.append(update.reaction)
    if not sets:
        return {"status": "no changes"}
    params.append(notification_id)
    await db.execute(
        f"UPDATE notifications SET {', '.join(sets)} WHERE id = ?",
        tuple(params),
    )
    return {"status": "ok"}
```

Register the router in the app (check `odigos/main.py` or the router aggregator for the pattern).

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_notifications.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add odigos/core/notifier.py odigos/api/notifications.py tests/test_notifications.py
git commit -m "feat: unified notification system — persist, deliver, track, API endpoints"
```

---

### Task 7: ProactiveConfig

Add configuration for the proactive engine.

**Files:**
- Modify: `odigos/config.py`

- [ ] **Step 1: Add ProactiveConfig**

```python
class ProactiveConfig(BaseModel):
    enabled: bool = True
    interval_seconds: int = 900
    max_cycles_per_hour: int = 4
    max_per_cycle: int = 1
    safe_tools: list[str] = [
        "find_tools", "search", "scrape", "lookup_fact",
        "knowledge_lookup", "check_plan", "read_file",
    ]
```

Add to Settings: `proactive: ProactiveConfig = ProactiveConfig()`

- [ ] **Step 2: Commit**

```bash
git add odigos/config.py
git commit -m "feat: add ProactiveConfig section to settings"
```

---

### Task 8: Proactive Engine Pipeline

The core feature — replace idle_think with the 4-stage pipeline.

**Files:**
- Create: `odigos/core/heartbeat/proactive.py`
- Create: `tests/test_proactive.py`
- Modify: `odigos/core/heartbeat/orchestrator.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_proactive.py`:

1. `test_scan_brain_gaps` — create entities with no summary in DB, verify scan returns opportunities.
2. `test_scan_recent_conversations` — create recent conversation with a question, verify scan returns opportunity.
3. `test_prioritize_filters_thumbs_down` — create notification with reaction="not_relevant" for a source, verify prioritize filters it out.
4. `test_prioritize_selects_top_one` — provide 5 opportunities, verify only 1 selected.
5. `test_proactive_skips_when_disabled` — set proactive.enabled=False, verify pipeline returns immediately.

- [ ] **Step 2: Implement proactive.py**

Create `odigos/core/heartbeat/proactive.py`:

```python
"""Proactive agent pipeline — scan → prioritize → execute → publish.

Replaces idle_think. Runs when the heartbeat is idle and budget allows.
Stages 1-2 (scan+prioritize) run synchronously in the tick.
Stages 3-4 (execute+publish) run as an async background task.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.core.heartbeat.orchestrator import Heartbeat

logger = logging.getLogger(__name__)


@dataclass
class Opportunity:
    source: str
    title: str
    context: str
    priority_hint: float = 0.5
    conversation_id: str | None = None


# --- Stage 1: Signal Sources ---

async def scan_brain_gaps(hb: Heartbeat) -> list[Opportunity]:
    """Find entities with no summary, facts with no cross-references."""
    opportunities = []
    if not hb.db:
        return opportunities
    # Entities with no summary
    rows = await hb.db.fetch_all(
        "SELECT name, type FROM entities WHERE status = 'active' "
        "AND (summary IS NULL OR summary = '') LIMIT 5"
    )
    for r in rows:
        opportunities.append(Opportunity(
            source="brain_gaps",
            title=f"Research {r['name']}",
            context=f"Entity '{r['name']}' ({r['type']}) has no summary",
            priority_hint=0.5,
        ))
    return opportunities


async def scan_recent_conversations(hb: Heartbeat) -> list[Opportunity]:
    """Find topics from last 24h that weren't fully explored."""
    opportunities = []
    if not hb.db:
        return opportunities
    rows = await hb.db.fetch_all(
        "SELECT c.id, c.title, m.content FROM conversations c "
        "JOIN messages m ON m.conversation_id = c.id "
        "WHERE m.role = 'user' AND m.created_at > datetime('now', '-1 day') "
        "AND length(m.content) > 50 "
        "ORDER BY m.created_at DESC LIMIT 10"
    )
    for r in rows:
        opportunities.append(Opportunity(
            source="recent_conversations",
            title=f"Explore: {r['content'][:60]}",
            context=f"User asked about this in conversation {r['id'][:8]}",
            priority_hint=0.4,
            conversation_id=r["id"],
        ))
    return opportunities


async def scan_active_goals(hb: Heartbeat) -> list[Opportunity]:
    """Check active goals for progress opportunities."""
    opportunities = []
    if not hb.goal_store:
        return opportunities
    goals = await hb.goal_store.list_goals(status="active")
    for g in goals:
        opportunities.append(Opportunity(
            source="active_goals",
            title=f"Progress on: {g['description'][:60]}",
            context=f"Goal {g['id'][:8]}: {g.get('progress_note', 'no progress noted')}",
            priority_hint=0.6,
        ))
    return opportunities


SIGNAL_SOURCES = [
    scan_brain_gaps,
    scan_recent_conversations,
    scan_active_goals,
]


# --- Stage 2: Prioritize ---

async def prioritize(
    hb: Heartbeat,
    opportunities: list[Opportunity],
    diary_context: str = "",
) -> Opportunity | None:
    """Filter and rank opportunities. Returns top 1 or None."""
    if not opportunities:
        return None

    # Filter out topics user thumbs-downed
    if hb.db:
        suppressed = await hb.db.fetch_all(
            "SELECT source FROM notifications WHERE reaction = 'not_relevant' "
            "GROUP BY source HAVING SUM(CASE WHEN reaction='thumbs_up' THEN 1 "
            "WHEN reaction='not_relevant' THEN -1 ELSE 0 END) < -2"
        )
        suppressed_sources = {r["source"] for r in suppressed}
        opportunities = [o for o in opportunities if o.source not in suppressed_sources]

    if not opportunities:
        return None

    # If 3 or fewer, just take the highest priority_hint
    if len(opportunities) <= 3:
        return max(opportunities, key=lambda o: o.priority_hint)

    # More than 3: use a cheap LLM call to rank
    try:
        from odigos.core.llm_prompt import call_llm
        opp_text = "\n".join(
            f"{i+1}. [{o.source}] {o.title}: {o.context}"
            for i, o in enumerate(opportunities[:10])
        )
        prompt = (
            "Rank these opportunities by value to the user. "
            "Return the number of the most valuable one.\n\n"
            f"{opp_text}\n\n"
            f"Recent agent diary:\n{diary_context[:500]}\n\n"
            "Reply with just the number."
        )
        resp = await call_llm(
            hb.provider, [{"role": "user", "content": prompt}],
            max_tokens=10, temperature=0.1,
            model=getattr(hb, "_background_model", None),
        )
        if resp and resp.content.strip().isdigit():
            idx = int(resp.content.strip()) - 1
            if 0 <= idx < len(opportunities):
                return opportunities[idx]
    except Exception:
        logger.debug("Proactive prioritize LLM call failed, using hint score")

    return max(opportunities, key=lambda o: o.priority_hint)


# --- Stage 3+4: Execute + Publish (async background task) ---

async def _execute_and_publish(hb: Heartbeat, opportunity: Opportunity) -> None:
    """Execute the opportunity and publish results. Runs as background task."""
    from odigos.channels.base import UniversalMessage
    from odigos.memory.brain_writer import BrainWriter
    from datetime import datetime, timezone
    import uuid

    try:
        # Build message for headless execution
        msg = UniversalMessage(
            id=uuid.uuid4().hex,
            channel="proactive",
            sender="system",
            content=f"Research and provide findings on: {opportunity.title}\n\nContext: {opportunity.context}",
            timestamp=datetime.now(timezone.utc),
            metadata={"conversation_id": opportunity.conversation_id or ""},
        )

        # Execute with safe tools only
        proactive_config = getattr(hb, "_proactive_config", None)
        safe_tools = proactive_config.safe_tools if proactive_config else [
            "find_tools", "search", "scrape", "lookup_fact", "knowledge_lookup",
        ]

        result = await hb.agent.handle_message(
            msg, headless=True,
            background_model=getattr(hb, "_background_model", ""),
        )

        if not result or len(result.strip()) < 20:
            logger.info("Proactive execution produced no useful result for: %s", opportunity.title)
            return

        # Publish via BrainWriter
        writer = BrainWriter()
        artifact_path = await writer.write_synthesis(
            title=opportunity.title,
            content=result,
            source=opportunity.source,
            source_context=opportunity.context,
            conversation_id=opportunity.conversation_id,
        )

        # Write diary entry
        await writer.append_diary(
            summary=f"Researched: {opportunity.title}. Produced synthesis at {artifact_path}.",
            open_threads="",
        )

        # Notify user
        if hb.notifier:
            await hb.notifier.notify(
                title=opportunity.title,
                body=result[:200],
                type="finding",
                artifact_path=artifact_path,
                conversation_id=opportunity.conversation_id,
                source=opportunity.source,
            )

        logger.info("Proactive cycle complete: %s → %s", opportunity.title, artifact_path)

    except Exception:
        logger.exception("Proactive execute/publish failed for: %s", opportunity.title)


# --- Main entry point ---

async def run_proactive(hb: Heartbeat) -> None:
    """Run the proactive pipeline. Called from heartbeat Phase 5."""
    # Check config
    proactive_config = getattr(hb, "_proactive_config", None)
    if proactive_config and not proactive_config.enabled:
        return

    # Rate limit
    now = time.monotonic()
    interval = proactive_config.interval_seconds if proactive_config else 900
    if now - hb._last_idle < interval:
        return
    hb._last_idle = now

    # Check hourly cycle limit
    # (simplified: just use the interval to naturally limit)

    # Stage 1: Scan
    all_opportunities: list[Opportunity] = []
    results = await asyncio.gather(
        *[source(hb) for source in SIGNAL_SOURCES],
        return_exceptions=True,
    )
    for result in results:
        if isinstance(result, list):
            all_opportunities.extend(result)

    if not all_opportunities:
        return

    # Read diary for context
    diary_context = ""
    from pathlib import Path
    diary_path = Path("data/agent/diary.md")
    if diary_path.exists():
        lines = diary_path.read_text(encoding="utf-8").split("\n")
        diary_context = "\n".join(lines[-30:])  # Last ~5 entries

    # Stage 2: Prioritize
    selected = await prioritize(hb, all_opportunities, diary_context)
    if not selected:
        return

    logger.info("Proactive: selected '%s' from %d opportunities", selected.title, len(all_opportunities))

    # Stages 3+4: Execute + Publish (async, doesn't block tick)
    asyncio.create_task(_execute_and_publish(hb, selected))
```

- [ ] **Step 3: Update orchestrator to use proactive pipeline**

In `odigos/core/heartbeat/orchestrator.py`:

Replace the Phase 5 block:
```python
# Phase 5: Idle thoughts (LLM calls)
if not did_work and not _over_budget:
    await idle.idle_think(self)
```

With:
```python
# Phase 5: Proactive pipeline (scan → prioritize → execute → publish)
if not did_work and not _over_budget:
    from odigos.core.heartbeat import proactive
    await proactive.run_proactive(self)
```

Remove `idle` from the top-level import on line 7.

Add `self._proactive_config` to the constructor, wired from settings in bootstrap.

- [ ] **Step 4: Remove idle.py**

```bash
git rm odigos/core/heartbeat/idle.py
```

Keep `odigos/core/idle_research.py` — it's a helper module still useful for the `scan_recent_conversations` scanner.

- [ ] **Step 5: Run tests**

Run: `python3 -m pytest tests/test_proactive.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add odigos/core/heartbeat/proactive.py tests/test_proactive.py odigos/core/heartbeat/orchestrator.py
git commit -m "feat: proactive pipeline replaces idle_think — scan, prioritize, execute, publish"
```

---

### Task 9: Wire Bootstrap + Switch Callback/Background Notifications

Wire proactive config, update directory creation, and consolidate notification callers.

**Files:**
- Modify: `odigos/bootstrap.py`
- Modify: `odigos/api/callbacks.py`
- Modify: `odigos/core/heartbeat/background.py`

- [ ] **Step 1: Update bootstrap directory creation**

Replace `data/wiki` paths with `data/brain`:
```python
Path("data/brain/entities").mkdir(parents=True, exist_ok=True)
Path("data/brain/topics").mkdir(parents=True, exist_ok=True)
Path("data/brain/conversations").mkdir(parents=True, exist_ok=True)
Path("data/brain/synthesis").mkdir(parents=True, exist_ok=True)
Path("data/agent").mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 2: Wire proactive config to heartbeat**

Where the Heartbeat is constructed in bootstrap.py, add:
```python
heartbeat._proactive_config = self.settings.proactive
```

- [ ] **Step 3: Register notifications router**

Find where API routers are registered and add:
```python
from odigos.api.notifications import router as notifications_router
app.include_router(notifications_router)
```

- [ ] **Step 4: Update callbacks.py**

The callback completion handler currently calls `container.message_bus.publish()` which handles notification via the bus. Add an explicit notification for the user-facing feed:

```python
if container.notifier:
    await container.notifier.notify(
        title=f"{task['tool_name']} complete",
        body=result.data[:200],
        type="status",
        conversation_id=conversation_id,
        source="background_task",
    )
```

- [ ] **Step 5: Update background.py**

Same pattern — add explicit Notifier.notify() call for completed background tasks.

- [ ] **Step 6: Commit**

```bash
git add odigos/bootstrap.py odigos/api/callbacks.py odigos/core/heartbeat/background.py
git commit -m "feat: wire proactive config, notification router, consolidated notify callers"
```

---

### Task 10: Deploy and Smoke Test

**Files:** No changes — runtime verification.

- [ ] **Step 1: Run full test suite**

Run: `python3 -m pytest tests/test_brain_writer.py tests/test_brain_reader.py tests/test_proactive.py tests/test_notifications.py tests/test_message_bus.py tests/test_extractor.py -q`
Expected: All pass

- [ ] **Step 2: Push and deploy**

```bash
git push origin main
ssh root@82.25.91.86 "cd /opt/odigos && git fetch origin main && git reset --hard origin/main && chown -R odigos_agent:odigos_agent . && rm -f data/odigos.db data/odigos.db-shm data/odigos.db-wal && rm -rf data/wiki && cd dashboard && npm run build 2>&1 | tail -3 && cd .. && chown -R odigos_agent:odigos_agent . && systemctl restart odigos"
```

Note: `rm -rf data/wiki` removes old directory. `rm -f data/odigos.db*` fresh DB with new schema. No migration — clean deploy.

- [ ] **Step 3: Verify brain directories created**

```bash
ssh root@82.25.91.86 "ls -la /opt/odigos/data/brain/ && ls -la /opt/odigos/data/agent/"
```

- [ ] **Step 4: Send messages and verify extraction + brain writes**

Send a few messages to Bob. Wait 30s for brain_maintenance. Check:
```bash
ssh root@82.25.91.86 "find /opt/odigos/data/brain -name '*.md' && cat /opt/odigos/data/brain/log.md"
```

- [ ] **Step 5: Wait for proactive cycle and verify**

Wait 15 minutes (or temporarily reduce interval). Check:
```bash
ssh root@82.25.91.86 "cat /opt/odigos/data/agent/diary.md && find /opt/odigos/data/brain/synthesis -name '*.md' && sqlite3 /opt/odigos/data/odigos.db 'SELECT type, title, source FROM notifications LIMIT 5'"
```

- [ ] **Step 6: Verify notification API**

```bash
ssh root@82.25.91.86 "curl -s -H 'Authorization: Bearer API_KEY' http://127.0.0.1:8000/api/notifications | head -50"
```
