"""MemoryEvolution — heartbeat job for refining and consolidating memories."""
from __future__ import annotations

import json
import logging
import re
import struct
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.db import Database
    from odigos.providers.embeddings import EmbeddingProvider

logger = logging.getLogger(__name__)

MAX_QUEUE_PER_CYCLE = 5
MAX_CONSOLIDATE_PER_CYCLE = 3
CONSOLIDATION_LINK_THRESHOLD = 4


def _serialize_f32(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


class MemoryEvolution:
    """Heartbeat job: process evolution queue + consolidate high-connectivity memories."""

    def __init__(
        self,
        db: "Database",
        llm_client,
        prompts_dir: str = "data/prompts",
        embedder: "EmbeddingProvider | None" = None,
    ) -> None:
        self._db = db
        self._llm = llm_client
        self._prompts_dir = Path(prompts_dir)
        self._embedder = embedder

    async def run_cycle(self) -> dict:
        """Run one evolution cycle. Returns stats."""
        processed = await self._process_queue()
        consolidated = await self._consolidate_high_connectivity()
        return {"processed": processed, "consolidated": consolidated}

    async def _process_queue(self) -> int:
        rows = await self._db.fetch_all(
            "SELECT eq.*, m.content as existing_content, m.memory_type, "
            "m.context_description as existing_context, m.keywords_json "
            "FROM evolution_queue eq "
            "JOIN memories m ON m.id = eq.existing_memory_id "
            "WHERE eq.processed_at IS NULL AND m.status = 'active' "
            "ORDER BY eq.created_at ASC LIMIT ?",
            (MAX_QUEUE_PER_CYCLE,),
        )
        if not rows:
            return 0

        count = 0
        for row in rows:
            try:
                await self._evolve_one(row)
                count += 1
            except Exception:
                logger.debug("Evolution failed for queue item %s", row["id"], exc_info=True)

            now = datetime.now(timezone.utc).isoformat()
            await self._db.execute(
                "UPDATE evolution_queue SET processed_at = ? WHERE id = ?",
                (now, row["id"]),
            )
        return count

    async def _evolve_one(self, row) -> None:
        prompt = self._load_prompt("memory_evolve.md")
        filled = prompt.format(
            memory_type=row["memory_type"],
            existing_content=row["existing_content"][:500],
            existing_context=(row["existing_context"] or "")[:300],
            existing_keywords=row["keywords_json"] or "[]",
            new_content=row["new_content"][:500],
        )

        response = await self._llm.complete(
            messages=[{"role": "system", "content": filled}],
            temperature=0.3, max_tokens=800,
        )
        parsed = self._parse_json(response.content)
        action = parsed.get("action", "SKIP")

        if action == "UPDATE":
            now = datetime.now(timezone.utc).isoformat()
            updates = []
            params = []
            if parsed.get("context_description"):
                updates.append("context_description = ?")
                params.append(parsed["context_description"])
            if parsed.get("keywords"):
                updates.append("keywords_json = ?")
                params.append(json.dumps(parsed["keywords"]))
            if parsed.get("tags"):
                updates.append("tags_json = ?")
                params.append(json.dumps(parsed["tags"]))
            updates.append("updated_at = ?")
            params.append(now)
            params.append(row["existing_memory_id"])

            if updates:
                await self._db.execute(
                    f"UPDATE memories SET {', '.join(updates)} WHERE id = ?",
                    tuple(params),
                )

        elif action == "SUPERSEDE":
            new_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()
            await self._db.execute(
                """INSERT INTO memories (id, content, memory_type, keywords_json,
                   tags_json, context_description, source_type, source_id, confidence)
                VALUES (?, ?, ?, ?, ?, ?, 'evolution', ?, 0.8)""",
                (
                    new_id,
                    parsed.get("content", row["new_content"]),
                    parsed.get("memory_type", row["memory_type"]),
                    json.dumps(parsed.get("keywords", [])),
                    json.dumps(parsed.get("tags", [])),
                    parsed.get("context_description", ""),
                    row["existing_memory_id"],
                ),
            )

            # Embed new memory if embedder available
            if self._embedder:
                embed_text = parsed.get("context_description", parsed.get("content", ""))
                vec = await self._embedder.embed(embed_text)
                try:
                    await self._db.execute(
                        "INSERT INTO memory_vec (id, embedding) VALUES (?, ?)",
                        (new_id, _serialize_f32(vec)),
                    )
                except Exception:
                    logger.debug("memory_vec insert skipped (extension unavailable)", exc_info=True)

            # Mark old as superseded
            await self._db.execute(
                "UPDATE memories SET status = 'superseded', superseded_by = ?, "
                "updated_at = ? WHERE id = ?",
                (new_id, now, row["existing_memory_id"]),
            )

            # Transfer links to new memory
            await self._db.execute(
                "UPDATE memory_links SET source_note_id = ? WHERE source_note_id = ?",
                (new_id, row["existing_memory_id"]),
            )
            await self._db.execute(
                "UPDATE memory_links SET target_note_id = ? WHERE target_note_id = ?",
                (new_id, row["existing_memory_id"]),
            )

    async def _consolidate_high_connectivity(self) -> int:
        """Find memories with 4+ links and attempt synthesis."""
        rows = await self._db.fetch_all(
            """
            SELECT m.id, m.content, m.memory_type, m.context_description,
                   COUNT(ml.id) as link_count
            FROM memories m
            JOIN memory_links ml ON ml.target_note_id = m.id
            WHERE m.status = 'active'
            GROUP BY m.id
            HAVING link_count >= ?
            ORDER BY link_count DESC
            LIMIT ?
            """,
            (CONSOLIDATION_LINK_THRESHOLD, MAX_CONSOLIDATE_PER_CYCLE),
        )
        if not rows:
            return 0

        count = 0
        for row in rows:
            try:
                did = await self._consolidate_one(row)
                if did:
                    count += 1
            except Exception:
                logger.debug("Consolidation failed for %s", row["id"], exc_info=True)
        return count

    async def _consolidate_one(self, row) -> bool:
        # Fetch connected memories
        connected = await self._db.fetch_all(
            """
            SELECT m.id, m.content, m.memory_type, m.context_description
            FROM memories m
            JOIN memory_links ml ON m.id = ml.source_note_id
            WHERE ml.target_note_id = ? AND m.status = 'active'
            LIMIT 10
            """,
            (row["id"],),
        )
        if len(connected) < 2:
            return False

        lines = []
        for c in connected:
            lines.append(
                f"- [{c['memory_type']}] {(c['context_description'] or c['content'])[:200]}"
            )

        prompt = self._load_prompt("memory_consolidate.md")
        filled = prompt.format(
            memory_type=row["memory_type"],
            content=row["content"][:500],
            context_description=(row["context_description"] or "")[:300],
            connected_block="\n".join(lines),
        )

        response = await self._llm.complete(
            messages=[{"role": "system", "content": filled}],
            temperature=0.3, max_tokens=800,
        )
        parsed = self._parse_json(response.content)

        if not parsed.get("should_consolidate"):
            return False

        new_id = str(uuid.uuid4())
        await self._db.execute(
            """INSERT INTO memories (id, content, memory_type, keywords_json,
               tags_json, context_description, source_type, source_id, confidence)
            VALUES (?, ?, ?, ?, ?, ?, 'synthesis', ?, 0.9)""",
            (
                new_id,
                parsed.get("content", ""),
                parsed.get("memory_type", "fact"),
                json.dumps(parsed.get("keywords", [])),
                json.dumps(parsed.get("tags", [])),
                parsed.get("context_description", ""),
                row["id"],
            ),
        )

        if self._embedder:
            vec = await self._embedder.embed(
                parsed.get("context_description", parsed.get("content", ""))
            )
            try:
                await self._db.execute(
                    "INSERT INTO memory_vec (id, embedding) VALUES (?, ?)",
                    (new_id, _serialize_f32(vec)),
                )
            except Exception:
                logger.debug("memory_vec insert skipped (extension unavailable)", exc_info=True)

        # Link synthesized memory to originals
        all_ids = [row["id"]] + [c["id"] for c in connected]
        for orig_id in all_ids:
            await self._db.execute(
                "INSERT OR IGNORE INTO memory_links "
                "(source_note_id, target_note_id, relationship, strength) "
                "VALUES (?, ?, 'synthesized_from', 1.0)",
                (new_id, orig_id),
            )

        return True

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
