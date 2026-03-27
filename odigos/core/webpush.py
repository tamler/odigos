"""Web Push notification support."""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

VAPID_KEYS_PATH = Path("data/vapid_keys.json")


def get_or_create_vapid_keys() -> dict:
    """Get existing VAPID keys or generate new ones."""
    if VAPID_KEYS_PATH.exists():
        return json.loads(VAPID_KEYS_PATH.read_text())

    try:
        from py_vapid import Vapid

        vapid = Vapid()
        vapid.generate_keys()
        keys = {
            "private_key": vapid.private_pem().decode(),
            "public_key": vapid.public_key_urlsafe_base64(),
        }
        VAPID_KEYS_PATH.parent.mkdir(parents=True, exist_ok=True)
        VAPID_KEYS_PATH.write_text(json.dumps(keys))
        logger.info("Generated new VAPID keys")
        return keys
    except ImportError:
        logger.warning(
            "pywebpush not installed, push notifications disabled"
        )
        return {}


async def send_push_notification(
    subscription: dict,
    title: str,
    body: str,
    vapid_private_key: str,
    vapid_claims: dict,
) -> bool:
    """Send a push notification to a subscription endpoint."""
    try:
        from pywebpush import webpush
        import asyncio

        payload = json.dumps({
            "title": title,
            "body": body,
            "icon": "/icon-192.png",
            "badge": "/icon-192.png",
            "tag": "odigos-notification",
            "renotify": True,
        })

        await asyncio.to_thread(
            webpush,
            subscription_info=subscription,
            data=payload,
            vapid_private_key=vapid_private_key,
            vapid_claims=vapid_claims,
        )
        return True
    except ImportError:
        logger.debug("pywebpush not installed")
        return False
    except Exception as e:
        logger.warning("Push notification failed: %s", e)
        return False
