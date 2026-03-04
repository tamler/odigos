import json
import uuid

from odigos.db import Database


class EntityGraph:
    """Query helpers for the entity-relationship graph tables."""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def create_entity(
        self,
        entity_type: str,
        name: str,
        properties: dict | None = None,
        confidence: float = 1.0,
        source: str | None = None,
    ) -> str:
        """Create a new entity. Returns the entity ID."""
        entity_id = str(uuid.uuid4())
        await self.db.execute(
            "INSERT INTO entities (id, type, name, properties_json, confidence, source) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                entity_id,
                entity_type,
                name,
                json.dumps(properties) if properties else None,
                confidence,
                source,
            ),
        )
        return entity_id

    async def get_entity(self, entity_id: str) -> dict | None:
        """Get a single entity by ID."""
        return await self.db.fetch_one(
            "SELECT * FROM entities WHERE id = ?", (entity_id,)
        )

    async def find_entity(self, name: str) -> list[dict]:
        """Find entities by exact name or alias match."""
        # Exact name match
        results = await self.db.fetch_all(
            "SELECT * FROM entities WHERE name = ? AND status = 'active'", (name,)
        )
        if results:
            return results

        # Alias match (search aliases_json)
        all_with_aliases = await self.db.fetch_all(
            "SELECT * FROM entities WHERE aliases_json IS NOT NULL AND status = 'active'"
        )
        matches = []
        for row in all_with_aliases:
            aliases = json.loads(row["aliases_json"])
            if name in aliases:
                matches.append(row)
        return matches

    async def update_entity(
        self,
        entity_id: str,
        name: str | None = None,
        aliases: list[str] | None = None,
        properties: dict | None = None,
        confidence: float | None = None,
        summary: str | None = None,
    ) -> None:
        """Update entity fields. Only provided fields are updated."""
        updates = []
        params = []

        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if aliases is not None:
            updates.append("aliases_json = ?")
            params.append(json.dumps(aliases))
        if properties is not None:
            updates.append("properties_json = ?")
            params.append(json.dumps(properties))
        if confidence is not None:
            updates.append("confidence = ?")
            params.append(confidence)
        if summary is not None:
            updates.append("summary = ?")
            params.append(summary)

        if not updates:
            return

        updates.append("updated_at = datetime('now')")
        params.append(entity_id)

        await self.db.execute(
            f"UPDATE entities SET {', '.join(updates)} WHERE id = ?",
            tuple(params),
        )

    async def create_edge(
        self,
        source_id: str,
        relationship: str,
        target_id: str,
        metadata: dict | None = None,
        strength: float = 1.0,
    ) -> int:
        """Create an edge between two entities. Returns the edge ID."""
        cursor = await self.db.conn.execute(
            "INSERT INTO edges (source_id, relationship, target_id, strength, "
            "metadata_json, last_confirmed) VALUES (?, ?, ?, ?, ?, datetime('now'))",
            (
                source_id,
                relationship,
                target_id,
                strength,
                json.dumps(metadata) if metadata else None,
            ),
        )
        await self.db.conn.commit()
        return cursor.lastrowid

    async def get_related(self, entity_id: str) -> list[dict]:
        """Get all entities one hop away from the given entity."""
        return await self.db.fetch_all(
            """
            SELECT DISTINCT e.* FROM entities e
            JOIN edges ON (
                (edges.source_id = ? AND edges.target_id = e.id) OR
                (edges.target_id = ? AND edges.source_id = e.id)
            )
            WHERE e.status = 'active'
            """,
            (entity_id, entity_id),
        )

    async def traverse(self, entity_id: str, depth: int = 2) -> list[dict]:
        """Multi-hop traversal using recursive CTE. Returns all reachable entities."""
        return await self.db.fetch_all(
            """
            WITH RECURSIVE reachable(id, depth) AS (
                -- Seed: direct neighbors
                SELECT CASE
                    WHEN edges.source_id = ? THEN edges.target_id
                    ELSE edges.source_id
                END, 1
                FROM edges
                WHERE edges.source_id = ? OR edges.target_id = ?

                UNION

                -- Recurse
                SELECT CASE
                    WHEN edges.source_id = reachable.id THEN edges.target_id
                    ELSE edges.source_id
                END, reachable.depth + 1
                FROM edges
                JOIN reachable ON (
                    edges.source_id = reachable.id OR edges.target_id = reachable.id
                )
                WHERE reachable.depth < ?
            )
            SELECT DISTINCT e.* FROM entities e
            JOIN reachable ON e.id = reachable.id
            WHERE e.id != ? AND e.status = 'active'
            """,
            (entity_id, entity_id, entity_id, depth, entity_id),
        )

    async def merge_entities(self, keep_id: str, remove_id: str) -> None:
        """Merge remove_id into keep_id: reassign edges, combine aliases, delete duplicate."""
        keep = await self.get_entity(keep_id)
        remove = await self.get_entity(remove_id)
        if not keep or not remove:
            return

        # Combine aliases
        keep_aliases = json.loads(keep["aliases_json"]) if keep["aliases_json"] else []
        remove_aliases = json.loads(remove["aliases_json"]) if remove["aliases_json"] else []
        combined = list(set(keep_aliases + remove_aliases + [remove["name"]]))
        await self.update_entity(keep_id, aliases=combined)

        # Reassign edges
        await self.db.execute(
            "UPDATE edges SET source_id = ? WHERE source_id = ?",
            (keep_id, remove_id),
        )
        await self.db.execute(
            "UPDATE edges SET target_id = ? WHERE target_id = ?",
            (keep_id, remove_id),
        )

        # Delete the removed entity
        await self.db.execute("DELETE FROM entities WHERE id = ?", (remove_id,))
