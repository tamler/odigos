"""MessageBus — single interface for all conversation message publishing.

Every message in the system flows through bus.publish(). No other code
writes directly to the messages table. The bus writes to DB (source of
truth) and pushes to all registered channel adapters.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.channels.base import ChannelRegistry
    from odigos.db import Database


class MessageBus:
    def __init__(self, db: Database, channel_registry: ChannelRegistry):
        self.db = db
        self.channel_registry = channel_registry

    async def create_conversation(self, channel: str, title: str | None = None) -> str:
        """Create a new conversation. Returns the conversation ID (plain UUID)."""
        conv_id = uuid.uuid4().hex
        await self.db.execute(
            "INSERT INTO conversations (id, channel, title) VALUES (?, ?, ?)",
            (conv_id, channel, title),
        )
        return conv_id

    async def publish(
        self,
        conversation_id: str,
        role: str,
        content: str,
        channel: str = "system",
        message_type: str = "chat",
        model_used: str | None = None,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
        cost_usd: float | None = None,
        metadata: dict | None = None,
        idempotency_key: str | None = None,
        message_id: str | None = None,
    ) -> str:
        """Publish a message. Writes to DB + pushes to all registered channels.

        Returns the message ID. Pass message_id for pre-allocated IDs (streaming
        correlation). If idempotency_key is provided and already exists, returns
        the existing message ID without creating a duplicate.
        """
        # Idempotency check (callbacks may fire twice)
        if idempotency_key:
            existing = await self.db.fetch_one(
                "SELECT id FROM messages WHERE json_extract(metadata_json, '$.idempotency_key') = ?",
                (idempotency_key,),
            )
            if existing:
                return existing["id"]
            metadata = {**(metadata or {}), "idempotency_key": idempotency_key}

        # 1. Write to DB (source of truth)
        msg_id = message_id or uuid.uuid4().hex
        await self.db.execute(
            "INSERT INTO messages (id, conversation_id, role, content, channel, "
            "message_type, model_used, tokens_in, tokens_out, cost_usd, metadata_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (msg_id, conversation_id, role, content, channel, message_type,
             model_used, tokens_in, tokens_out, cost_usd,
             json.dumps(metadata) if metadata else None),
        )

        # 2. Update conversation metadata
        await self.db.execute(
            "UPDATE conversations SET message_count = message_count + 1, "
            "last_message_at = datetime('now'), updated_at = datetime('now') "
            "WHERE id = ?",
            (conversation_id,),
        )

        # 3. Create delivery rows for ALL registered channels, push to reachable ones
        msg_data = {
            "type": "message",
            "id": msg_id,
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
            "channel": channel,
            "message_type": message_type,
            "metadata": metadata,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        for ch in self.channel_registry.all():
            delivery_id = uuid.uuid4().hex
            delivered_at = None
            try:
                if ch.is_reachable():
                    await ch.deliver(msg_data)
                    delivered_at = datetime.now(timezone.utc).isoformat()
            except Exception:
                pass  # Channel error, delivery stays pending
            await self.db.execute(
                "INSERT INTO message_deliveries (id, message_id, channel, delivered_at) "
                "VALUES (?, ?, ?, ?)",
                (delivery_id, msg_id, ch.channel_name, delivered_at),
            )

        return msg_id
