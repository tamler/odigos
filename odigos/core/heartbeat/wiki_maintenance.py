"""Heartbeat phase 3d: drain pending_wiki_writes queue and project entity wiki pages."""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.core.heartbeat.orchestrator import Heartbeat

logger = logging.getLogger(__name__)


async def run_wiki_maintenance(hb: Heartbeat) -> bool:
    """Drain pending_wiki_writes and project entity data into wiki markdown files."""
    try:
        return await _do_wiki_maintenance(hb)
    except Exception:
        logger.exception("Wiki maintenance failed")
        return False


async def _do_wiki_maintenance(hb: Heartbeat) -> bool:
    from odigos.memory.wiki_writer import WikiWriter

    # 1. Fetch pending writes
    rows = await hb.db.fetch_all(
        "SELECT * FROM pending_wiki_writes ORDER BY created_at LIMIT 50"
    )
    if not rows:
        return False

    writer = WikiWriter()

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
                "SELECT * FROM user_facts WHERE fact LIKE ? LIMIT 20",
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
                    "SELECT id FROM user_facts WHERE fact LIKE ? LIMIT 20",
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
            logger.exception("Wiki maintenance: failed processing entity %s", entity_id)

    # 5. Rebuild wiki/index.md
    try:
        all_entities = await hb.db.fetch_all(
            "SELECT * FROM entities WHERE status = 'active' ORDER BY name"
        )
        # Mark which have pages
        for e in all_entities:
            e_facts = await hb.db.fetch_all(
                "SELECT id FROM user_facts WHERE fact LIKE ? LIMIT 5",
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
        logger.exception("Wiki maintenance: failed rebuilding index")

    # 6. Append to wiki/log.md
    try:
        details = f"Processed {len(rows)} pending writes, {len(entity_ids)} entities"
        await writer.append_log("wiki_maintenance", details)
    except Exception:
        logger.exception("Wiki maintenance: failed writing log")

    # 7. Delete processed rows
    try:
        ids = [row["id"] for row in rows]
        placeholders = ",".join("?" for _ in ids)
        await hb.db.execute(
            f"DELETE FROM pending_wiki_writes WHERE id IN ({placeholders})",
            tuple(ids),
        )
    except Exception:
        logger.exception("Wiki maintenance: failed deleting processed rows")

    return True


async def run_wiki_lint(hb: Heartbeat) -> bool:
    """Lint pass: find orphan entities with no edges older than 7 days."""
    try:
        return await _do_wiki_lint(hb)
    except Exception:
        logger.exception("Wiki lint failed")
        return False


async def _do_wiki_lint(hb: Heartbeat) -> bool:
    from odigos.memory.wiki_writer import WikiWriter

    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")

    orphans = await hb.db.fetch_all(
        "SELECT e.id, e.name, e.type, e.created_at FROM entities e "
        "WHERE e.status = 'active' "
        "AND e.created_at < ? "
        "AND NOT EXISTS (SELECT 1 FROM edges WHERE source_id = e.id OR target_id = e.id)",
        (cutoff,),
    )

    if not orphans:
        return False

    writer = WikiWriter()
    names = [o.get("name", "?") for o in orphans]
    details = f"Found {len(orphans)} orphan entities (no edges, >7 days old): {', '.join(names[:20])}"
    await writer.append_log("wiki_lint", details)
    logger.info("Wiki lint: %s", details)

    return True
