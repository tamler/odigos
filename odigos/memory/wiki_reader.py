"""Parse wiki files to reconstruct DB tables on empty startup.

The wiki is the durable human-readable knowledge base. When the DB is lost,
these functions rebuild the operational tables from the wiki files generated
by wiki_writer.py and source_archiver.py.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def _parse_frontmatter(text: str) -> dict:
    """Extract key-value pairs from YAML frontmatter between --- delimiters."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}

    fm_lines: list[str] = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        fm_lines.append(line)

    result: dict = {}
    for line in fm_lines:
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()

        # Parse list values like [Jake, J] or [conv:abc123, conv:def456]
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            if inner:
                result[key] = [item.strip() for item in inner.split(", ") if item.strip()]
            else:
                result[key] = []
        else:
            result[key] = value
    return result


def _extract_section(text: str, heading: str) -> list[str]:
    """Extract bullet lines from a markdown section (## heading)."""
    pattern = rf"^## {re.escape(heading)}\s*$"
    match = re.search(pattern, text, re.MULTILINE)
    if not match:
        return []

    start = match.end()
    # Find next heading or end of text
    next_heading = re.search(r"^## ", text[start:], re.MULTILINE)
    if next_heading:
        section = text[start : start + next_heading.start()]
    else:
        section = text[start:]

    lines = []
    for line in section.strip().split("\n"):
        line = line.strip()
        if line.startswith("- "):
            lines.append(line[2:])
    return lines


def _extract_name_from_heading(text: str) -> str:
    """Extract entity name from the first # heading."""
    match = re.search(r"^# (.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else "unknown"


def parse_entity_page(filepath: Path) -> dict:
    """Parse a wiki entity page.

    Returns dict with keys:
        id, type, name, aliases, confidence, sources, facts, relationships.
    """
    text = filepath.read_text(encoding="utf-8")
    fm = _parse_frontmatter(text)

    name = _extract_name_from_heading(text)

    # Parse confidence as float
    confidence = 0.0
    if "confidence" in fm:
        try:
            confidence = float(fm["confidence"])
        except (ValueError, TypeError):
            confidence = 0.0

    # Parse facts with optional source citations
    facts = []
    for line in _extract_section(text, "Facts"):
        # Pattern: fact text [source_type:source_id]
        citation_match = re.search(r"\s+\[(\w+):([^\]]+)\]\s*$", line)
        if citation_match:
            fact_text = line[: citation_match.start()]
            source_type = citation_match.group(1)
            source_id = citation_match.group(2)
            facts.append({
                "fact": fact_text,
                "source_type": source_type,
                "source_id": source_id,
            })
        else:
            facts.append({"fact": line, "source_type": None, "source_id": None})

    # Parse forward relationships: **verb** -> target
    relationships = []
    for line in _extract_section(text, "Relationships"):
        rel_match = re.match(r"\*\*(.+?)\*\* -> (.+)$", line)
        if rel_match:
            relationships.append({
                "relationship": rel_match.group(1),
                "to": rel_match.group(2).strip(),
                "direction": "forward",
            })

    # Parse backlinks: source **verb** -> thisEntity
    for line in _extract_section(text, "Backlinks"):
        bl_match = re.match(r"(.+?) \*\*(.+?)\*\* -> (.+)$", line)
        if bl_match:
            relationships.append({
                "from": bl_match.group(1).strip(),
                "relationship": bl_match.group(2),
                "to": bl_match.group(3).strip(),
                "direction": "backlink",
            })

    return {
        "id": fm.get("id", ""),
        "type": fm.get("type", "unknown"),
        "name": name,
        "aliases": fm.get("aliases", []),
        "confidence": confidence,
        "sources": fm.get("sources", []),
        "facts": facts,
        "relationships": relationships,
    }


def parse_topic_index(filepath: Path) -> list[dict]:
    """Parse ungraduated entities from a topic index's ## Index section.

    Returns list of dicts with keys: name, type, summary, sources.
    """
    text = filepath.read_text(encoding="utf-8")
    fm = _parse_frontmatter(text)
    entity_type = fm.get("entity_type", "unknown")

    results = []
    for line in _extract_section(text, "Index"):
        # Pattern: **Name** -- summary [source_type:source_id]
        # or: **Name** [source_type:source_id]
        # or: **Name** -- summary
        name_match = re.match(r"\*\*(.+?)\*\*(.*)$", line)
        if not name_match:
            continue

        name = name_match.group(1)
        rest = name_match.group(2).strip()

        summary = ""
        source_type = None
        source_id = None

        # Extract trailing citation
        citation_match = re.search(r"\s*\[(\w+):([^\]]+)\]\s*$", rest)
        if citation_match:
            source_type = citation_match.group(1)
            source_id = citation_match.group(2)
            rest = rest[: citation_match.start()].strip()

        # Extract summary after --
        if rest.startswith("-- "):
            summary = rest[3:].strip()
        elif rest.startswith("--"):
            summary = rest[2:].strip()

        entry: dict = {"name": name, "type": entity_type, "summary": summary}
        if source_type and source_id:
            entry["sources"] = [f"{source_type}:{source_id}"]
        else:
            entry["sources"] = []
        results.append(entry)

    return results


def _parse_source_frontmatter(filepath: Path) -> dict | None:
    """Parse a source archive file's frontmatter for url and title."""
    try:
        text = filepath.read_text(encoding="utf-8")
    except Exception:
        return None
    fm = _parse_frontmatter(text)
    if not fm:
        return None
    return {
        "url": fm.get("url", ""),
        "title": fm.get("title", ""),
        "content_hash": fm.get("sha256", ""),
        "filename": filepath.name,
    }


async def rebuild_from_wiki(db, wiki_dir: Path) -> dict:
    """Rebuild DB tables from wiki files.

    Returns stats dict: {"entities": N, "facts": N, "edges": N, "sources": N}
    """
    stats = {"entities": 0, "facts": 0, "edges": 0, "sources": 0}
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Track entity names to IDs for relationship resolution
    name_to_id: dict[str, str] = {}

    # 1. Parse entity pages
    entities_dir = wiki_dir / "entities"
    if entities_dir.exists():
        for filepath in sorted(entities_dir.glob("*.md")):
            try:
                entity = parse_entity_page(filepath)
            except Exception:
                logger.warning("Failed to parse entity page: %s", filepath)
                continue

            entity_id = entity["id"] or uuid.uuid4().hex[:12]
            import json
            aliases_json = json.dumps(entity["aliases"]) if entity["aliases"] else None

            await db.execute(
                "INSERT OR IGNORE INTO entities "
                "(id, type, name, aliases_json, confidence, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'active', ?, ?)",
                (
                    entity_id,
                    entity["type"],
                    entity["name"],
                    aliases_json,
                    entity["confidence"],
                    now,
                    now,
                ),
            )
            name_to_id[entity["name"]] = entity_id
            stats["entities"] += 1

            # 3. Parse facts
            for fact in entity["facts"]:
                fact_id = uuid.uuid4().hex[:12]
                await db.execute(
                    "INSERT OR IGNORE INTO user_facts "
                    "(id, fact, category, source, source_type, source_id, "
                    "confidence, created_at, updated_at) "
                    "VALUES (?, ?, 'general', 'wiki_rebuild', ?, ?, ?, ?, ?)",
                    (
                        fact_id,
                        fact["fact"],
                        fact.get("source_type"),
                        fact.get("source_id"),
                        entity["confidence"],
                        now,
                        now,
                    ),
                )
                stats["facts"] += 1

            # 4. Parse relationships (forward only — backlinks are the inverse)
            for rel in entity["relationships"]:
                if rel["direction"] == "forward":
                    # target may not exist yet — store name, resolve later
                    target_name = rel["to"]
                    target_id = name_to_id.get(target_name)
                    if not target_id:
                        # Create a stub entity for the target
                        target_id = uuid.uuid4().hex[:12]
                        await db.execute(
                            "INSERT OR IGNORE INTO entities "
                            "(id, type, name, confidence, status, created_at, updated_at) "
                            "VALUES (?, 'unknown', ?, 0.5, 'active', ?, ?)",
                            (target_id, target_name, now, now),
                        )
                        name_to_id[target_name] = target_id

                    await db.execute(
                        "INSERT INTO edges (source_id, relationship, target_id, strength, "
                        "created_at) VALUES (?, ?, ?, 1.0, ?)",
                        (entity_id, rel["relationship"], target_id, now),
                    )
                    stats["edges"] += 1

    # 2. Parse topic indexes for ungraduated entities
    topics_dir = wiki_dir / "topics"
    if topics_dir.exists():
        for filepath in sorted(topics_dir.glob("*.md")):
            try:
                indexed = parse_topic_index(filepath)
            except Exception:
                logger.warning("Failed to parse topic index: %s", filepath)
                continue

            for entry in indexed:
                if entry["name"] in name_to_id:
                    continue  # Already exists from entity pages
                entity_id = uuid.uuid4().hex[:12]
                await db.execute(
                    "INSERT OR IGNORE INTO entities "
                    "(id, type, name, summary, confidence, status, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, 0.5, 'active', ?, ?)",
                    (entity_id, entry["type"], entry["name"], entry["summary"], now, now),
                )
                name_to_id[entry["name"]] = entity_id
                stats["entities"] += 1

    # 5. Parse source files
    sources_dir = wiki_dir.parent / "sources"
    if sources_dir.exists():
        for filepath in sorted(sources_dir.glob("*.md")):
            source = _parse_source_frontmatter(filepath)
            if not source:
                continue
            doc_id = uuid.uuid4().hex[:12]
            await db.execute(
                "INSERT OR IGNORE INTO documents "
                "(id, filename, source_url, content_hash, status) "
                "VALUES (?, ?, ?, ?, 'ingested')",
                (doc_id, source["filename"], source["url"], source["content_hash"]),
            )
            stats["sources"] += 1

    logger.info(
        "Wiki rebuild complete: %d entities, %d facts, %d edges, %d sources",
        stats["entities"],
        stats["facts"],
        stats["edges"],
        stats["sources"],
    )
    return stats
