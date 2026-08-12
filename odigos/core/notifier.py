"""Proactive notification system for pushing messages to users."""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from odigos.core.capabilities import record_degraded

if TYPE_CHECKING:
    from odigos.channels.base import ChannelRegistry
    from odigos.db import Database

logger = logging.getLogger(__name__)


class Notifier:
    """Sends notifications to channels and web push subscribers.

    Used by the cron system, heartbeat, and other features to proactively
    push information to users across all registered channels.
    """

    def __init__(
        self,
        channel_registry: ChannelRegistry,
        db: Database | None = None,
        vapid_keys: dict | None = None,
    ) -> None:
        self.channel_registry = channel_registry
        self.db = db
        self.vapid_keys = vapid_keys or {}

    async def notify(
        self,
        title: str,
        body: str,
        *,
        type: str = "status",
        artifact_path: str | None = None,
        conversation_id: str | None = None,
        source: str | None = None,
        channels: list[str] | None = None,
    ) -> str:
        """Persist notification + push to all channels. Returns notification ID."""
        import uuid as _uuid
        notif_id = _uuid.uuid4().hex

        # Persist to DB
        if self.db:
            try:
                await self.db.execute(
                    "INSERT INTO notifications (id, type, title, body, artifact_path, "
                    "conversation_id, source) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (notif_id, type, title, body, artifact_path, conversation_id, source),
                )
            except Exception:
                logger.debug("Failed to persist notification", exc_info=True)

        text = f"{title}\n\n{body}" if title else body

        if channels:
            targets = []
            for name in channels:
                ch = self.channel_registry.get(name)
                if ch:
                    targets.append(ch)
                else:
                    logger.warning(
                        "Notification channel not found: %s", name
                    )
        else:
            targets = self.channel_registry.all()

        for channel in targets:
            try:
                await channel.notify(
                    title=title,
                    body=body,
                    conversation_id=conversation_id,
                )
            except NotImplementedError:
                if conversation_id:
                    try:
                        await channel.send_message(
                            conversation_id, text[:4000]
                        )
                    except (NotImplementedError, Exception):
                        logger.debug(
                            "Channel '%s' does not support "
                            "send_message either",
                            channel.channel_name,
                        )
            except Exception:
                logger.exception(
                    "Failed to send notification via channel '%s'",
                    channel.channel_name,
                )

        # Send web push notifications to all stored subscriptions
        await self._send_push_notifications(title, body)

        return notif_id

    async def _send_push_notifications(
        self, title: str, body: str
    ) -> None:
        """Send push notifications to all stored subscriptions."""
        if not self.db or not self.vapid_keys:
            return

        private_key = self.vapid_keys.get("private_key", "")
        if not private_key:
            return

        try:
            from odigos.core.webpush import send_push_notification
        except ImportError as e:
            # This imports a first-party module, so a failure here means the
            # tree is broken, not that an optional extra is absent. Returning
            # silently made push notifications a no-op with no breadcrumb.
            record_degraded("odigos.core.webpush", e)
            return

        vapid_claims = {"sub": "mailto:noreply@odigos.one"}

        try:
            rows = await self.db.fetch_all(
                "SELECT endpoint, subscription_json "
                "FROM push_subscriptions"
            )
        except Exception:
            logger.debug("push_subscriptions table not ready")
            return

        for row in rows:
            try:
                subscription = json.loads(row["subscription_json"])
            except (json.JSONDecodeError, KeyError):
                continue

            ok = await send_push_notification(
                subscription=subscription,
                title=title,
                body=body,
                vapid_private_key=private_key,
                vapid_claims=vapid_claims,
            )
            if not ok:
                # Remove expired/invalid subscriptions
                try:
                    await self.db.execute(
                        "DELETE FROM push_subscriptions "
                        "WHERE endpoint = ?",
                        (row["endpoint"],),
                    )
                except Exception:
                    pass
