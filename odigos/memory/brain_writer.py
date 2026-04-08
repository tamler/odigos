"""Write entity pages, topic indexes, index.md, log.md, and conversation summaries to data/brain/.

The brain is the human-readable and LLM-readable knowledge base surface.
Heartbeat maintenance calls these methods; the brain reader parses the output.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def _slugify(text: str, max_len: int = 60) -> str:
    """Convert text to a filesystem-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:max_len]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_aliases(aliases_json: str | None) -> list[str]:
    if not aliases_json:
        return []
    try:
        parsed = json.loads(aliases_json)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _source_ref(source_type: str | None, source_id: str | None) -> str:
    if not source_id:
        return ""
    prefix = source_type or "conv"
    return f"[{prefix}:{source_id}]"


def _collect_sources(facts: list[dict], entity: dict | None = None) -> list[str]:
    """Collect unique source references from facts and optionally from the entity itself."""
    sources: list[str] = []
    seen: set[str] = set()
    items = list(facts)
    if entity and entity.get("source_id"):
        items.append(entity)
    for item in items:
        ref = _source_ref(item.get("source_type"), item.get("source_id"))
        if ref and ref not in seen:
            sources.append(ref)
            seen.add(ref)
    return sources


class BrainWriter:
    def __init__(self, brain_dir: Path | None = None):
        self.brain_dir = brain_dir or Path("data/brain")

    async def write_entity_page(
        self,
        entity: dict,
        facts: list[dict],
        relationships: list[dict],
    ) -> str:
        """Write a full entity page to brain/entities/{slug}.md. Returns filepath."""
        entities_dir = self.brain_dir / "entities"
        entities_dir.mkdir(parents=True, exist_ok=True)

        name = entity.get("name", "unknown")
        slug = _slugify(name)
        filepath = entities_dir / f"{slug}.md"

        aliases = _parse_aliases(entity.get("aliases_json"))
        confidence = entity.get("confidence", 0.0)
        sources = _collect_sources(facts, entity)
        entity_type = entity.get("type", "unknown")
        entity_id = entity.get("id", "")

        # Frontmatter
        lines = [
            "---",
            f"id: {entity_id}",
            f"type: {entity_type}",
            f"aliases: [{', '.join(aliases)}]",
            f"confidence: {confidence}",
            f"sources: [{', '.join(sources)}]",
            f"updated_at: {_now_iso()}",
            "---",
            "",
            f"# {name}",
            "",
        ]

        # Facts section
        if facts:
            lines.append("## Facts")
            for f in facts:
                ref = _source_ref(f.get("source_type"), f.get("source_id"))
                ref_str = f" {ref}" if ref else ""
                lines.append(f"- {f['fact']}{ref_str}")
            lines.append("")

        # Split relationships into forward and backlinks
        forward = [r for r in relationships if r.get("direction") != "backlink"]
        backlinks = [r for r in relationships if r.get("direction") == "backlink"]

        if forward:
            lines.append("## Relationships")
            for r in forward:
                lines.append(f"- **{r['relationship']}** -> {r['to']}")
            lines.append("")

        if backlinks:
            lines.append("## Backlinks")
            for r in backlinks:
                lines.append(f"- {r['from']} **{r['relationship']}** -> {name}")
            lines.append("")

        filepath.write_text("\n".join(lines))
        logger.info("Wrote entity page: %s", filepath)
        return str(filepath)

    async def write_topic_index(
        self,
        entity_type: str,
        graduated: list[dict],
        indexed: list[dict],
    ) -> str:
        """Write a topic index to brain/topics/{type}.md. Returns filepath."""
        topics_dir = self.brain_dir / "topics"
        topics_dir.mkdir(parents=True, exist_ok=True)

        slug = _slugify(entity_type)
        filepath = topics_dir / f"{slug}.md"

        title = entity_type.replace("_", " ").title()

        lines = [
            "---",
            "type: topic_index",
            f"entity_type: {entity_type}",
            f"updated_at: {_now_iso()}",
            "---",
            "",
            f"# {title}",
            "",
        ]

        if graduated:
            lines.append("## Full Pages")
            for e in graduated:
                name = e.get("name", "unknown")
                desc = e.get("description", "")
                entity_slug = _slugify(name)
                desc_str = f" -- {desc}" if desc else ""
                lines.append(f"- [{name}](../entities/{entity_slug}.md){desc_str}")
            lines.append("")

        if indexed:
            lines.append("## Index")
            for e in indexed:
                name = e.get("name", "unknown")
                desc = e.get("description", "")
                ref = _source_ref(e.get("source_type"), e.get("source_id"))
                desc_str = f" -- {desc}" if desc else ""
                ref_str = f" {ref}" if ref else ""
                lines.append(f"- **{name}**{desc_str}{ref_str}")
            lines.append("")

        filepath.write_text("\n".join(lines))
        logger.info("Wrote topic index: %s", filepath)
        return str(filepath)

    async def write_index(
        self,
        all_entities: list[dict],
        topic_types: list[str],
    ) -> str:
        """Regenerate brain/index.md -- master catalog."""
        self.brain_dir.mkdir(parents=True, exist_ok=True)
        filepath = self.brain_dir / "index.md"

        lines = [
            "---",
            f"updated_at: {_now_iso()}",
            f"entity_count: {len(all_entities)}",
            "---",
            "",
            "# Knowledge Base Index",
            "",
        ]

        # Topics section
        if topic_types:
            lines.append("## Topics")
            for t in topic_types:
                slug = _slugify(t)
                title = t.replace("_", " ").title()
                count = sum(1 for e in all_entities if e.get("type") == t)
                lines.append(f"- [{title}](topics/{slug}.md) -- {count} entities")
            lines.append("")

        # All entities
        if all_entities:
            lines.append("## All Entities")
            for e in all_entities:
                name = e.get("name", "unknown")
                etype = e.get("type", "unknown")
                desc = e.get("description", "")
                has_page = e.get("has_page", False)
                desc_str = f" -- {desc}" if desc else ""
                if has_page:
                    entity_slug = _slugify(name)
                    lines.append(
                        f"- **{name}** ({etype}){desc_str} [entities/{entity_slug}.md]"
                    )
                else:
                    lines.append(f"- **{name}** ({etype}){desc_str}")
            lines.append("")

        filepath.write_text("\n".join(lines))
        logger.info("Wrote index: %s", filepath)
        return str(filepath)

    async def append_log(self, operation: str, details: str) -> None:
        """Append an entry to brain/log.md with timestamp prefix."""
        self.brain_dir.mkdir(parents=True, exist_ok=True)
        filepath = self.brain_dir / "log.md"

        entry = f"## [{_now_iso()}] {operation}\n{details}\n\n"

        if filepath.exists():
            existing = filepath.read_text()
            filepath.write_text(entry + existing)
        else:
            filepath.write_text(entry)

        logger.info("Appended log: %s", operation)

    async def write_conversation_summary(
        self,
        conv_id: str,
        title: str,
        summary: str,
        message_count: int,
        created_at: str,
        facts_extracted: list[str],
    ) -> str:
        """Write a conversation summary to brain/conversations/{date}-{slug}.md."""
        convos_dir = self.brain_dir / "conversations"
        convos_dir.mkdir(parents=True, exist_ok=True)

        # Extract date from created_at (ISO format)
        date = created_at[:10] if created_at else datetime.now(timezone.utc).strftime("%Y-%m-%d")
        slug = _slugify(title) if title else _slugify(conv_id)
        filepath = convos_dir / f"{date}-{slug}.md"

        lines = [
            "---",
            f"id: {conv_id}",
            f"message_count: {message_count}",
            f"created_at: {created_at}",
            "---",
            "",
            f"# {title}",
            "",
            summary,
            "",
        ]

        if facts_extracted:
            lines.append("## Key Facts Extracted")
            for fact in facts_extracted:
                lines.append(f"- {fact}")
            lines.append("")

        filepath.write_text("\n".join(lines))
        logger.info("Wrote conversation summary: %s", filepath)
        return str(filepath)

    def should_graduate(self, fact_count: int, relationship_count: int) -> bool:
        """Entity graduates to full page at 3+ facts or 2+ relationships."""
        return fact_count >= 3 or relationship_count >= 2

    async def write_synthesis(self, title: str, content: str, source: str,
                               source_context: str, conversation_id: str | None = None) -> str:
        """Write a proactive finding to brain/synthesis/. Returns filepath."""
        synth_dir = self.brain_dir / "synthesis"
        synth_dir.mkdir(parents=True, exist_ok=True)
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        slug = _slugify(title)
        filepath = synth_dir / f"{date}-{slug}.md"
        counter = 1
        while filepath.exists():
            filepath = synth_dir / f"{date}-{slug}-{counter}.md"
            counter += 1
        now = _now_iso()
        fm = f"---\ntype: finding\ntitle: {title}\nsource: {source}\nsource_context: {source_context}\n"
        if conversation_id:
            fm += f"conversation_id: {conversation_id}\n"
        fm += f"created_at: {now}\n---\n\n"
        filepath.write_text(fm + f"# {title}\n\n{content}\n", encoding="utf-8")
        logger.info("Wrote synthesis: %s", filepath.name)
        return str(filepath)

    async def write_source(self, content: str, title: str, url: str | None = None,
                            content_type: str = "article") -> str | None:
        """Write external content to data/sources/. Returns filepath or None if duplicate."""
        import hashlib
        sources_dir = Path("data/sources")
        sources_dir.mkdir(parents=True, exist_ok=True)
        sha = hashlib.sha256(content.encode()).hexdigest()
        for existing in sources_dir.glob("*.md"):
            try:
                header = existing.read_text(encoding="utf-8")[:500]
                if f"sha256: {sha}" in header:
                    return None
            except Exception:
                continue
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        slug = _slugify(title) if title else _slugify(url or "untitled")
        filepath = sources_dir / f"{date}-{slug}.md"
        counter = 1
        while filepath.exists():
            filepath = sources_dir / f"{date}-{slug}-{counter}.md"
            counter += 1
        now = _now_iso()
        fm = f"---\nurl: {url or ''}\ntitle: {title}\nscraped_at: {now}\ncontent_type: {content_type}\nsha256: {sha}\n---\n\n"
        filepath.write_text(fm + content, encoding="utf-8")
        logger.info("Archived source: %s", filepath.name)
        return str(filepath)

    async def append_diary(self, summary: str, open_threads: str = "") -> None:
        """Append an entry to data/agent/diary.md."""
        diary_dir = Path("data/agent")
        diary_dir.mkdir(parents=True, exist_ok=True)
        diary_path = diary_dir / "diary.md"
        now = _now_iso()
        entry = f"\n## [{now}] proactive_cycle\n{summary}\n"
        if open_threads:
            entry += f"Open threads: {open_threads}\n"
        with open(diary_path, "a", encoding="utf-8") as f:
            f.write(entry)
