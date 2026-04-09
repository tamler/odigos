"""Heartbeat phase 3d: drain pending_brain_writes queue and project entity brain pages."""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.core.heartbeat.orchestrator import Heartbeat

logger = logging.getLogger(__name__)


async def run_brain_maintenance(hb: Heartbeat) -> bool:
    """Drain pending_brain_writes and project entity data into brain markdown files."""
    try:
        return await _do_brain_maintenance(hb)
    except Exception:
        logger.exception("Brain maintenance failed")
        return False


async def _do_brain_maintenance(hb: Heartbeat) -> bool:
    from odigos.memory.brain_writer import BrainWriter

    # 1. Fetch pending writes
    rows = await hb.db.fetch_all(
        "SELECT * FROM pending_brain_writes ORDER BY created_at LIMIT 50"
    )
    if not rows:
        return False

    writer = BrainWriter()

    # 2. Collect unique entity_ids from pending writes
    entity_ids: set[str] = set()
    for row in rows:
        eid = row.get("entity_id")
        if eid:
            entity_ids.add(eid)
        # If only fact_id, look up which entity it references
        fid = row.get("fact_id")
        if fid and not eid:
            # Facts reference entities by name in the text; we still process the write
            # but we can't determine entity_id from fact alone without extra lookup.
            # These will be caught on the next pass when the entity itself is queued.
            pass

    graduated_entities: list[dict] = []
    all_topic_types: set[str] = set()

    # 3. Process each entity
    for entity_id in entity_ids:
        try:
            entities = await hb.db.fetch_all(
                "SELECT * FROM entities WHERE id = ?", (entity_id,)
            )
            if not entities:
                continue
            entity = entities[0]
            entity_name = entity.get("name", "")
            entity_type = entity.get("type", "unknown")
            all_topic_types.add(entity_type)

            # Fetch related facts
            facts = await hb.db.fetch_all(
                "SELECT id, content as fact, source_type as category, confidence FROM memories "
                "WHERE memory_type = 'fact' AND status = 'active' AND content LIKE ? LIMIT 20",
                (f"%{entity_name}%",),
            )

            # Fetch outgoing edges
            outgoing = await hb.db.fetch_all(
                "SELECT e.*, t.name as target_name "
                "FROM edges e JOIN entities t ON e.target_id = t.id "
                "WHERE e.source_id = ?",
                (entity_id,),
            )

            # Fetch incoming edges (backlinks)
            incoming = await hb.db.fetch_all(
                "SELECT e.*, s.name as source_name "
                "FROM edges e JOIN entities s ON e.source_id = s.id "
                "WHERE e.target_id = ?",
                (entity_id,),
            )

            # Build relationships list for WikiWriter
            relationships: list[dict] = []
            for edge in outgoing:
                relationships.append({
                    "relationship": edge.get("relationship", "related_to"),
                    "to": edge.get("target_name", "unknown"),
                    "direction": "outgoing",
                })
            for edge in incoming:
                relationships.append({
                    "relationship": edge.get("relationship", "related_to"),
                    "from": edge.get("source_name", "unknown"),
                    "direction": "backlink",
                })

            fact_count = len(facts)
            rel_count = len(outgoing) + len(incoming)

            if writer.should_graduate(fact_count, rel_count):
                await writer.write_entity_page(entity, facts, relationships)
                entity["has_page"] = True
                graduated_entities.append(entity)
            else:
                entity["has_page"] = False

            # 4. Update topic index for this entity's type
            type_entities = await hb.db.fetch_all(
                "SELECT * FROM entities WHERE type = ? AND status = 'active' "
                "ORDER BY name",
                (entity_type,),
            )
            graduated_for_type = []
            indexed_for_type = []
            for e in type_entities:
                e_facts = await hb.db.fetch_all(
                    "SELECT id FROM memories WHERE memory_type = 'fact' AND status = 'active' AND content LIKE ? LIMIT 20",
                    (f"%{e.get('name', '')}%",),
                )
                e_edges = await hb.db.fetch_all(
                    "SELECT id FROM edges WHERE source_id = ? OR target_id = ?",
                    (e["id"], e["id"]),
                )
                if writer.should_graduate(len(e_facts), len(e_edges)):
                    e["has_page"] = True
                    graduated_for_type.append(e)
                else:
                    e["has_page"] = False
                    indexed_for_type.append(e)

            await writer.write_topic_index(entity_type, graduated_for_type, indexed_for_type)

        except Exception:
            logger.exception("Brain maintenance: failed processing entity %s", entity_id)

    # 5. Rebuild wiki/index.md
    try:
        all_entities = await hb.db.fetch_all(
            "SELECT * FROM entities WHERE status = 'active' ORDER BY name"
        )
        # Mark which have pages
        for e in all_entities:
            e_facts = await hb.db.fetch_all(
                "SELECT id FROM memories WHERE memory_type = 'fact' AND status = 'active' AND content LIKE ? LIMIT 5",
                (f"%{e.get('name', '')}%",),
            )
            e_edges = await hb.db.fetch_all(
                "SELECT id FROM edges WHERE source_id = ? OR target_id = ?",
                (e["id"], e["id"]),
            )
            e["has_page"] = writer.should_graduate(len(e_facts), len(e_edges))

        topic_types = list(
            {e.get("type", "unknown") for e in all_entities}
        )
        topic_types.sort()
        await writer.write_index(all_entities, topic_types)
    except Exception:
        logger.exception("Brain maintenance: failed rebuilding index")

    # 6. Append to wiki/log.md
    try:
        details = f"Processed {len(rows)} pending writes, {len(entity_ids)} entities"
        await writer.append_log("brain_maintenance", details)
    except Exception:
        logger.exception("Brain maintenance: failed writing log")

    # 7. Delete processed rows
    try:
        ids = [row["id"] for row in rows]
        placeholders = ",".join("?" for _ in ids)
        await hb.db.execute(
            f"DELETE FROM pending_brain_writes WHERE id IN ({placeholders})",
            tuple(ids),
        )
    except Exception:
        logger.exception("Brain maintenance: failed deleting processed rows")

    return True


async def run_brain_lint(hb: Heartbeat) -> bool:
    """Lint pass: orphan entities, experience PRUNE/MERGE."""
    try:
        return await _do_brain_lint(hb)
    except Exception:
        logger.exception("Brain lint failed")
        return False


async def _do_brain_lint(hb: Heartbeat) -> bool:
    from odigos.memory.brain_writer import BrainWriter

    findings: list[str] = []

    # 1. Orphan entities (no edges, older than 7 days)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    orphans = await hb.db.fetch_all(
        "SELECT e.id, e.name, e.type FROM entities e "
        "WHERE e.status = 'active' AND e.created_at < ? "
        "AND NOT EXISTS (SELECT 1 FROM edges WHERE source_id = e.id OR target_id = e.id)",
        (cutoff,),
    )
    for o in orphans:
        findings.append(f"Orphan entity: {o['name']} ({o['type']})")

    # 2. Experience PRUNE — stale (14 days unused) and low-confidence
    stale = await hb.db.fetch_all(
        "SELECT id, lesson FROM agent_experiences "
        "WHERE times_applied = 0 AND created_at < datetime('now', '-14 days')"
    )
    for exp in stale:
        await hb.db.execute("DELETE FROM agent_experiences WHERE id = ?", (exp["id"],))
        findings.append(f"Pruned stale experience: {exp['lesson'][:60]}")

    low_conf = await hb.db.fetch_all(
        "SELECT id, lesson FROM agent_experiences "
        "WHERE confidence < 0.3 AND times_applied < 2"
    )
    for exp in low_conf:
        await hb.db.execute("DELETE FROM agent_experiences WHERE id = ?", (exp["id"],))
        findings.append(f"Pruned low-confidence experience: {exp['lesson'][:60]}")

    # 3. Experience MERGE — consolidate near-duplicate lessons per tool
    tools = await hb.db.fetch_all("SELECT DISTINCT tool_name FROM agent_experiences")
    for tool in tools:
        exps = await hb.db.fetch_all(
            "SELECT id, lesson, confidence FROM agent_experiences "
            "WHERE tool_name = ? ORDER BY confidence DESC",
            (tool["tool_name"],),
        )
        if len(exps) < 2:
            continue
        seen: list[dict] = []
        for exp in exps:
            words_a = set(exp["lesson"].lower().split())
            is_dup = False
            for kept in seen:
                words_b = set(kept["lesson"].lower().split())
                union = words_a | words_b
                if union and len(words_a & words_b) / len(union) > 0.6:
                    await hb.db.execute("DELETE FROM agent_experiences WHERE id = ?", (exp["id"],))
                    findings.append(f"Merged duplicate experience: {exp['lesson'][:40]}")
                    is_dup = True
                    break
            if not is_dup:
                seen.append(dict(exp))

    if not findings:
        return False

    writer = BrainWriter()
    await writer.append_log("brain_lint", "\n".join(findings))
    logger.info("Brain lint: %d findings", len(findings))
    return True
