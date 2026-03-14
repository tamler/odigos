"""Proactive notification system for pushing messages to users."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.channels.base import ChannelRegistry

logger = logging.getLogger(__name__)


class Notifier:
    """Sends notifications to channels.

    Used by the cron system, heartbeat, and other features to proactively
    push information to users across all registered channels.
    """

    def __init__(self, channel_registry: ChannelRegistry) -> None:
        self.channel_registry = channel_registry

    async def notify(
        self,
        title: str,
        body: str,
        conversation_id: str | None = None,
        channels: list[str] | None = None,
    ) -> None:
        """Send a notification to specified channels (or all).

        Args:
            title: Short notification title.
            body: Notification body text.
            conversation_id: Optional conversation to target.
            channels: Optional list of channel names. If None, sends to all.
        """
        text = f"{title}\n\n{body}" if title else body

        if channels:
            targets = []
            for name in channels:
                ch = self.channel_registry.get(name)
                if ch:
                    targets.append(ch)
                else:
                    logger.warning("Notification channel not found: %s", name)
        else:
            targets = self.channel_registry.all()

        for channel in targets:
            try:
                await channel.notify(title=title, body=body, conversation_id=conversation_id)
            except NotImplementedError:
                # Channel does not support notify — fall back to send_message if we have a conversation_id
                if conversation_id:
                    try:
                        await channel.send_message(conversation_id, text[:4000])
                    except (NotImplementedError, Exception):
                        logger.debug(
                            "Channel '%s' does not support send_message either",
                            channel.channel_name,
                        )
            except Exception:
                logger.exception(
                    "Failed to send notification via channel '%s'",
                    channel.channel_name,
                )
