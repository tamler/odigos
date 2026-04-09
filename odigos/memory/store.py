"""MemoryStore — structured memory write pipeline."""
from __future__ import annotations

import json
import logging
import re
import struct
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.db import Database
    from odigos.providers.embeddings import EmbeddingProvider

from odigos.memory.classifier import ClassificationResult, MemoryClassifier

logger = logging.getLogger(__name__)

DEDUP_THRESHOLD = 0.15
LINK_THRESHOLD = 0.4
LINK_CANDIDATES = 5


def _serialize_f32(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


@dataclass
class MemoryRecord:
    id: str
    content: str
    memory_type: str
    keywords: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    context_description: str = ""
    source_type: str = ""
    source_id: str = ""
    conversation_id: str | None = None
    confidence: float = 0.8
    status: str = "active"


class MemoryStore:
    """Structured memory write pipeline: classify, embed, dedup, link."""

    def __init__(
        self,
        db: Database,
        llm_client,
        embedder: EmbeddingProvider,
        prompts_dir: str = "data/prompts",
    ) -> None:
        self._db = db
        self._llm = llm_client
        self._embedder = embedder
        self._classifier = MemoryClassifier(llm_client, prompts_dir)
        self._prompts_dir = Path(prompts_dir)
        self._vec_available: bool | None = None  # lazily determined

    async def _check_vec_available(self) -> bool:
        """Return True if memory_vec virtual table exists and is usable."""
        if self._vec_available is not None:
            return self._vec_available
        try:
            row = await self._db.fetch_one(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_vec'"
            )
            self._vec_available = row is not None
        except Exception:
            self._vec_available = False
        return self._vec_available

    async def store(
        self,
        content: str,
        source_type: str,
        source_id: str,
        conversation_id: str | None = None,
        confidence: float = 0.8,
        bulk: bool = False,
        classification: ClassificationResult | None = None,
    ) -> MemoryRecord:
        """Store a memory: classify, embed, dedup, link.

        Args:
            content: Raw content to store.
            source_type: Where this came from (conversation, document, etc.)
            source_id: ID of the source.
            conversation_id: Optional conversation reference.
            confidence: Initial confidence score.
            bulk: If True, skip link discovery (for bulk ingestion).
            classification: Pre-computed classification (for bulk document mode).
        """
        # 1. Classify
        if classification is None:
            classification = await self._classifier.classify(content)

        # 2. Embed (only if vec table is available)
        vec_available = await self._check_vec_available()
        vector: list[float] | None = None
        if vec_available:
            embed_text = classification.context_description or content
            vector = await self._embedder.embed(embed_text)

        # 3. Dedup check — exact-content first (no vec needed), then near-duplicate via vec
        existing = await self._find_exact_duplicate(content, classification.memory_type)
        if existing:
            return existing
        if vector is not None:
            existing = await self._find_near_duplicate(vector, classification.memory_type)
            if existing:
                return existing

        # 4. Store
        mem_id = str(uuid.uuid4())
        await self._db.execute(
            """
            INSERT INTO memories
                (id, content, memory_type, keywords_json, tags_json,
                 context_description, source_type, source_id,
                 conversation_id, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mem_id,
                content,
                classification.memory_type,
                json.dumps(classification.keywords),
                json.dumps(classification.tags),
                classification.context_description,
                source_type,
                source_id,
                conversation_id,
                confidence,
            ),
        )
        if vector is not None:
            await self._db.execute(
                "INSERT INTO memory_vec (id, embedding) VALUES (?, ?)",
                (mem_id, _serialize_f32(vector)),
            )

        record = MemoryRecord(
            id=mem_id,
            content=content,
            memory_type=classification.memory_type,
            keywords=classification.keywords,
            tags=classification.tags,
            context_description=classification.context_description,
            source_type=source_type,
            source_id=source_id,
            conversation_id=conversation_id,
            confidence=confidence,
        )

        # 5. Link discovery (skip in bulk mode, for summaries, or without vec)
        if not bulk and classification.memory_type != "summary" and vector is not None:
            await self._discover_links(record, vector)

        return record

    async def _find_exact_duplicate(
        self, content: str, memory_type: str,
    ) -> MemoryRecord | None:
        """Check for an exact content+type duplicate in the memories table."""
        row = await self._db.fetch_one(
            "SELECT * FROM memories WHERE content = ? AND memory_type = ? AND status = 'active'",
            (content, memory_type),
        )
        if row is None:
            return None
        return MemoryRecord(
            id=row["id"],
            content=row["content"],
            memory_type=row["memory_type"],
            keywords=json.loads(row["keywords_json"] or "[]"),
            tags=json.loads(row["tags_json"] or "[]"),
            context_description=row["context_description"] or "",
            source_type=row["source_type"],
            source_id=row["source_id"],
            confidence=row["confidence"],
            status=row["status"],
        )

    async def _find_near_duplicate(
        self, vector: list[float], memory_type: str,
    ) -> MemoryRecord | None:
        """Check for near-duplicate in vector store."""
        count = await self._db.fetch_one("SELECT COUNT(*) as c FROM memory_vec")
        if not count or count["c"] == 0:
            return None

        rows = await self._db.fetch_all(
            """
            SELECT m.*, v.distance FROM (
                SELECT id, distance FROM memory_vec
                WHERE embedding MATCH ? ORDER BY distance LIMIT 3
            ) v
            JOIN memories m ON m.id = v.id
            WHERE m.status = 'active'
            """,
            (_serialize_f32(vector),),
        )

        for row in rows:
            if row["distance"] < DEDUP_THRESHOLD:
                if row["memory_type"] == memory_type:
                    return MemoryRecord(
                        id=row["id"],
                        content=row["content"],
                        memory_type=row["memory_type"],
                        keywords=json.loads(row["keywords_json"] or "[]"),
                        tags=json.loads(row["tags_json"] or "[]"),
                        context_description=row["context_description"] or "",
                        source_type=row["source_type"],
                        source_id=row["source_id"],
                        confidence=row["confidence"],
                        status=row["status"],
                    )
                else:
                    # Type mismatch — queue for evolution
                    await self._db.execute(
                        "INSERT INTO evolution_queue (existing_memory_id, new_content, reason) "
                        "VALUES (?, ?, ?)",
                        (row["id"], row["content"], "type_mismatch"),
                    )
        return None

    async def _discover_links(
        self, record: MemoryRecord, vector: list[float],
    ) -> None:
        """Find and create links to related memories."""
        count = await self._db.fetch_one("SELECT COUNT(*) as c FROM memory_vec")
        if not count or count["c"] < 2:
            return

        rows = await self._db.fetch_all(
            """
            SELECT m.id, m.content, m.memory_type, m.context_description,
                   v.distance
            FROM (
                SELECT id, distance FROM memory_vec
                WHERE embedding MATCH ? ORDER BY distance LIMIT ?
            ) v
            JOIN memories m ON m.id = v.id
            WHERE m.status = 'active' AND m.id != ?
            """,
            (_serialize_f32(vector), LINK_CANDIDATES + 1, record.id),
        )

        candidates = [r for r in rows if r["distance"] < LINK_THRESHOLD]
        if not candidates:
            return

        lines = []
        for c in candidates:
            lines.append(
                f"- ID: {c['id']} | Type: {c['memory_type']} | "
                f"Content: {(c['context_description'] or c['content'])[:200]}"
            )
        candidates_block = "\n".join(lines)

        prompt = self._load_prompt("memory_link.md")
        filled = prompt.format(
            new_type=record.memory_type,
            new_content=record.content[:500],
            new_context=record.context_description[:300],
            candidates_block=candidates_block,
        )

        try:
            response = await self._llm.complete(
                messages=[{"role": "system", "content": filled}],
                temperature=0.2,
                max_tokens=500,
            )
            parsed = self._parse_json(response.content)
            links = parsed.get("links", [])

            for link in links:
                rel = link.get("relationship", "none")
                if rel == "none":
                    continue
                target_id = link.get("candidate_id")
                strength = link.get("strength", 0.5)
                if not target_id:
                    continue

                await self._db.execute(
                    "INSERT OR IGNORE INTO memory_links "
                    "(source_note_id, target_note_id, relationship, strength) "
                    "VALUES (?, ?, ?, ?)",
                    (record.id, target_id, rel, strength),
                )
                await self._db.execute(
                    "INSERT OR IGNORE INTO memory_links "
                    "(source_note_id, target_note_id, relationship, strength) "
                    "VALUES (?, ?, ?, ?)",
                    (target_id, record.id, rel, strength),
                )

                if rel == "contradicts":
                    await self._db.execute(
                        "UPDATE memories SET status = 'superseded', "
                        "superseded_by = ? WHERE id = ?",
                        (record.id, target_id),
                    )
        except Exception:
            logger.debug("Link discovery failed", exc_info=True)

    def _load_prompt(self, filename: str) -> str:
        path = self._prompts_dir / filename
        if path.exists():
            return path.read_text()
        return ""

    @staticmethod
    def _parse_json(content: str) -> dict:
        text = content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-z]*\n?", "", text, count=1)
            text = re.sub(r"\n?```\s*$", "", text.rstrip())
            text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {}
