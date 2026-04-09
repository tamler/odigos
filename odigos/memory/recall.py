"""MemoryRecall — structured memory read pipeline."""
from __future__ import annotations

import logging
import struct
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.db import Database
    from odigos.providers.embeddings import EmbeddingProvider

logger = logging.getLogger(__name__)

TYPE_ROUTING = {
    "simple": ["fact", "preference", "entity"],
    "standard": ["fact", "preference", "entity", "experience", "correction"],
    "complex": None,
    "planning": ["task", "idea", "experience", "fact", "entity"],
    "document_query": ["general", "summary", "fact"],
}

RECENCY_DECAY = {
    "preference": 0.01, "task": 0.01, "fact": 0.01,
    "entity": 0.002, "experience": 0.002,
    "summary": 0.0, "correction": 0.0,
    "idea": 0.005, "general": 0.005,
}

MIN_CONFIDENCE = 0.5
RRF_K = 60


def _serialize_f32(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


@dataclass
class MemoryResult:
    id: str
    content: str
    memory_type: str
    context_description: str = ""
    confidence: float = 0.8
    distance: float = 0.0
    score: float = 0.0
    source: str = ""
    updated_at: str = ""


class MemoryRecall:
    """Structured memory read pipeline: typed search, RRF, link expansion."""

    def __init__(self, db: "Database", embedder: "EmbeddingProvider") -> None:
        self._db = db
        self._embedder = embedder

    async def search(
        self,
        query: str,
        classification_type: str | None = None,
        memory_types: list[str] | None = None,
        limit: int = 10,
        expand_links: bool = True,
    ) -> list[MemoryResult]:
        """Search memories with type filtering, RRF, recency, and link expansion."""
        # Determine type filter
        if memory_types:
            types = memory_types
        elif classification_type:
            types = TYPE_ROUTING.get(classification_type)
        else:
            types = None

        # Parallel: vector + FTS
        vector = await self._embedder.embed_query(query)
        vec_results = await self._vector_search(vector, types, limit=20)
        fts_results = await self._fts_search(query, types, limit=20)

        # RRF fusion
        merged = self._rrf_merge(vec_results, fts_results)

        # Recency weighting
        self._apply_recency(merged)

        # Sort by score descending, apply confidence filter
        merged.sort(key=lambda r: r.score, reverse=True)
        filtered = [r for r in merged if r.confidence >= MIN_CONFIDENCE][:limit]

        # Link expansion
        if expand_links and filtered:
            linked = await self._expand_links(
                [r.id for r in filtered], limit=5,
            )
            # Add linked results that aren't already present
            existing_ids = {r.id for r in filtered}
            for lr in linked:
                if lr.id not in existing_ids:
                    filtered.append(lr)
                    existing_ids.add(lr.id)

        return filtered

    async def _vector_search(
        self, vector: list[float], types: list[str] | None, limit: int,
    ) -> list[MemoryResult]:
        # Check whether the sqlite-vec virtual table exists before querying
        vec_table = await self._db.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_vec'"
        )
        if vec_table is None:
            return []

        count = await self._db.fetch_one("SELECT COUNT(*) as c FROM memory_vec")
        if not count or count["c"] == 0:
            return []

        fetch_limit = limit * 3 if types else limit

        rows = await self._db.fetch_all(
            """
            SELECT m.id, m.content, m.memory_type, m.context_description,
                   m.confidence, m.updated_at, v.distance
            FROM (
                SELECT id, distance FROM memory_vec
                WHERE embedding MATCH ? ORDER BY distance LIMIT ?
            ) v
            JOIN memories m ON m.id = v.id
            WHERE m.status = 'active'
            """,
            (_serialize_f32(vector), fetch_limit),
        )

        results = []
        for row in rows:
            if types and row["memory_type"] not in types:
                continue
            results.append(MemoryResult(
                id=row["id"],
                content=row["content"],
                memory_type=row["memory_type"],
                context_description=row["context_description"] or "",
                confidence=row["confidence"],
                distance=row["distance"],
                source="vector",
                updated_at=row.get("updated_at", ""),
            ))
        return results[:limit]

    async def _fts_search(
        self, query: str, types: list[str] | None, limit: int,
    ) -> list[MemoryResult]:
        _RESERVED = {"AND", "OR", "NOT", "NEAR"}
        terms = []
        for word in query.split():
            cleaned = "".join(c for c in word if c.isalnum())
            if cleaned and cleaned.upper() not in _RESERVED:
                terms.append(cleaned)
        if not terms:
            return []

        fts_query = " OR ".join(terms)
        if len(terms) >= 2:
            phrase = " ".join(terms)
            fts_query = f'"{phrase}" OR {fts_query}'

        rows = await self._db.fetch_all(
            """
            SELECT m.id, m.content, m.memory_type, m.context_description,
                   m.confidence, m.updated_at, rank as distance
            FROM memory_fts
            JOIN memories m ON m.rowid = memory_fts.rowid
            WHERE memory_fts MATCH ? AND m.status = 'active'
            ORDER BY rank
            LIMIT ?
            """,
            (fts_query, limit * 3 if types else limit),
        )

        results = []
        for row in rows:
            if types and row["memory_type"] not in types:
                continue
            results.append(MemoryResult(
                id=row["id"],
                content=row["content"],
                memory_type=row["memory_type"],
                context_description=row["context_description"] or "",
                confidence=row["confidence"],
                distance=abs(row["distance"]),
                source="fts",
                updated_at=row.get("updated_at", ""),
            ))
        return results[:limit]

    def _rrf_merge(
        self, vec_results: list[MemoryResult], fts_results: list[MemoryResult],
    ) -> list[MemoryResult]:
        scores: dict[str, float] = {}
        result_map: dict[str, MemoryResult] = {}

        for rank, r in enumerate(vec_results):
            scores[r.id] = scores.get(r.id, 0) + 1.0 / (RRF_K + rank + 1)
            result_map[r.id] = r

        for rank, r in enumerate(fts_results):
            scores[r.id] = scores.get(r.id, 0) + 1.0 / (RRF_K + rank + 1)
            if r.id not in result_map:
                result_map[r.id] = r

        for mid, score in scores.items():
            result_map[mid].score = score

        return list(result_map.values())

    def _apply_recency(self, results: list[MemoryResult]) -> None:
        now = datetime.now(timezone.utc)
        for r in results:
            decay_rate = RECENCY_DECAY.get(r.memory_type, 0.005)
            if decay_rate == 0.0 or not r.updated_at:
                continue
            try:
                updated = datetime.fromisoformat(r.updated_at.replace("Z", "+00:00"))
                if updated.tzinfo is None:
                    updated = updated.replace(tzinfo=timezone.utc)
                days = (now - updated).total_seconds() / 86400
                r.score *= 1.0 / (1.0 + days * decay_rate)
            except (ValueError, TypeError):
                pass

    async def _expand_links(
        self, result_ids: list[str], limit: int = 5,
    ) -> list[MemoryResult]:
        if not result_ids:
            return []
        placeholders = ",".join("?" * len(result_ids))
        rows = await self._db.fetch_all(
            f"""
            SELECT m.id, m.content, m.memory_type, m.context_description,
                   m.confidence, ml.strength
            FROM memories m
            JOIN memory_links ml ON m.id = ml.target_note_id
            WHERE ml.source_note_id IN ({placeholders})
              AND m.status = 'active'
              AND m.confidence >= ?
              AND m.id NOT IN ({placeholders})
            ORDER BY ml.strength DESC
            LIMIT ?
            """,
            (*result_ids, MIN_CONFIDENCE, *result_ids, limit),
        )
        return [
            MemoryResult(
                id=row["id"],
                content=row["content"],
                memory_type=row["memory_type"],
                context_description=row["context_description"] or "",
                confidence=row["confidence"],
                source="link",
            )
            for row in rows
        ]

    @staticmethod
    def format_grouped(results: list[MemoryResult]) -> str:
        """Format results grouped by memory_type for the system prompt."""
        if not results:
            return ""

        TYPE_HEADERS = {
            "fact": "Facts", "preference": "Preferences",
            "task": "Tasks", "idea": "Ideas",
            "entity": "Related entities", "experience": "Experiences",
            "correction": "Learned corrections",
            "summary": "Relevant summaries", "general": "Other",
        }

        groups: dict[str, list[str]] = {}
        for r in results:
            header = TYPE_HEADERS.get(r.memory_type, "Other")
            text = r.context_description or r.content
            groups.setdefault(header, []).append(f"- {text}")

        sections = ["## Recalled knowledge\n"]
        for header in TYPE_HEADERS.values():
            if header in groups:
                sections.append(f"### {header}")
                sections.extend(groups[header])
                sections.append("")

        return "\n".join(sections).strip()
