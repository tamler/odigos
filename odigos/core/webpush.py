"""Web Push notification support."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from odigos.core.capabilities import record_degraded

logger = logging.getLogger(__name__)

from odigos.storage import VAPID_KEYS_PATH


def get_or_create_vapid_keys() -> dict:
    """Get existing VAPID keys or generate new ones."""
    if VAPID_KEYS_PATH.exists():
        return json.loads(VAPID_KEYS_PATH.read_text())

    try:
        import base64
        from py_vapid import Vapid
        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            PublicFormat,
        )

        vapid = Vapid()
        vapid.generate_keys()
        raw_pub = vapid.public_key.public_bytes(
            encoding=Encoding.X962,
            format=PublicFormat.UncompressedPoint,
        )
        pub_b64 = base64.urlsafe_b64encode(raw_pub).rstrip(b"=").decode()
        keys = {
            "private_key": vapid.private_pem().decode(),
            "public_key": pub_b64,
        }
        VAPID_KEYS_PATH.parent.mkdir(parents=True, exist_ok=True)
        VAPID_KEYS_PATH.write_text(json.dumps(keys))
        logger.info("Generated new VAPID keys")
        return keys
    except ImportError as exc:
        # Was `except (ImportError, Exception)`, which is just `except Exception`
        # -- the ImportError arm never applied and a missing declared dependency
        # was reported as a generic warning.
        record_degraded("py-vapid", exc)
        return {}
    except Exception as exc:
        logger.warning(
            "VAPID key generation failed, push notifications disabled: %s",
            exc,
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
    except ImportError as e:
        # pywebpush is declared in pyproject.toml, so this is a broken install.
        # At debug level, push notifications simply stopped working in silence.
        record_degraded("pywebpush", e)
        return False
    except Exception as e:
        logger.warning("Push notification failed: %s", e)
        return False
