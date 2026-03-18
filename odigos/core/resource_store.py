"""Generic async CRUD store over any SQLite table.

Usage:
    notebooks = ResourceStore(db, "notebooks")
    entries = ResourceStore(db, "notebook_entries", parent_key="notebook_id")
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone

from odigos.db import Database

logger = logging.getLogger(__name__)

_SAFE_IDENTIFIER = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _validate_identifier(name: str) -> str:
    """Ensure a column/table name is a safe SQL identifier."""
    if not _SAFE_IDENTIFIER.match(name):
        raise ValueError(f"Unsafe SQL identifier: {name!r}")
    return name


class ResourceStore:
    """Generic CRUD store for any SQLite-backed resource.

    Handles id generation, timestamps, filtering, and ordering.
    Feature-specific logic (validation, side effects) belongs in the API layer.
    """

    def __init__(self, db: Database, table: str, *, parent_key: str | None = None) -> None:
        self.db = db
        self.table = _validate_identifier(table)
        self.parent_key = parent_key

    async def create(self, **fields) -> str:
        """Insert a row with auto-generated id and timestamps. Returns the id."""
        row_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        fields["id"] = row_id
        fields["created_at"] = now
        fields["updated_at"] = now

        columns = ", ".join(_validate_identifier(k) for k in fields)
        placeholders = ", ".join("?" for _ in fields)
        values = tuple(fields.values())

        await self.db.execute(
            f"INSERT INTO {self.table} ({columns}) VALUES ({placeholders})",
            values,
        )
        logger.debug("Created %s row %s", self.table, row_id[:8])
        return row_id

    async def get(self, row_id: str) -> dict | None:
        """Fetch a single row by id."""
        return await self.db.fetch_one(
            f"SELECT * FROM {self.table} WHERE id = ?",
            (row_id,),
        )

    async def list(
        self,
        *,
        order_by: str = "created_at DESC",
        limit: int | None = None,
        **filters,
    ) -> list[dict]:
        """List rows with optional exact-match filters."""
        query = f"SELECT * FROM {self.table}"
        params: list = []

        if filters:
            clauses = []
            for col, val in filters.items():
                clauses.append(f"{_validate_identifier(col)} = ?")
                params.append(val)
            query += " WHERE " + " AND ".join(clauses)

        query += f" ORDER BY {order_by}"

        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)

        return await self.db.fetch_all(query, tuple(params))

    async def update(self, row_id: str, **fields) -> bool:
        """Update specific fields, auto-set updated_at. Returns True if row existed."""
        existing = await self.get(row_id)
        if not existing:
            return False

        fields["updated_at"] = datetime.now(timezone.utc).isoformat()
        set_clause = ", ".join(f"{_validate_identifier(col)} = ?" for col in fields)
        values = tuple(fields.values()) + (row_id,)

        await self.db.execute(
            f"UPDATE {self.table} SET {set_clause} WHERE id = ?",
            values,
        )
        logger.debug("Updated %s row %s", self.table, row_id[:8])
        return True

    async def delete(self, row_id: str) -> bool:
        """Delete a row by id. Returns True if row existed."""
        existing = await self.get(row_id)
        if not existing:
            return False

        await self.db.execute(
            f"DELETE FROM {self.table} WHERE id = ?",
            (row_id,),
        )
        logger.debug("Deleted %s row %s", self.table, row_id[:8])
        return True
