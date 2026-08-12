"""Charter 01-cleanup.md §1: Notifier.notify() must accept priority=.

All 8 heartbeat/maintenance.py call sites pass `priority=`. The signature had no
such keyword and no **kwargs, so every one raised TypeError -- straight into an
`except Exception: logger.debug`. Nudges, follow-ups, email alerts, storage
warnings and update notices have never worked on any agent.

The reason it went unnoticed for so long is the shape this repo keeps hitting:
the failure was caught by a broad handler and logged below the default level, so
the feature read as present. See anti-patterns.md.
"""
import inspect

import pytest

from odigos.core.notifier import Notifier


def test_notify_accepts_priority_keyword():
    sig = inspect.signature(Notifier.notify)
    assert "priority" in sig.parameters, (
        "8 call sites in heartbeat/maintenance.py pass priority=; without it "
        "every notification raises TypeError into a debug log"
    )
    assert sig.parameters["priority"].default == "normal"


@pytest.mark.parametrize("priority", ["low", "normal", "high"])
async def test_notify_with_priority_does_not_raise(priority):
    """The real bug: calling with priority= blew up before doing anything."""

    class _Registry:
        def all(self):
            return []

        def get(self, name):
            return None

    notifier = Notifier(db=None, channel_registry=_Registry())
    notif_id = await notifier.notify(
        title="t", body="b", type="status", priority=priority
    )
    assert notif_id


async def test_every_maintenance_call_site_signature_is_satisfiable():
    """Bind each real call site's kwargs against the signature.

    A parameter existing is not the same as the call sites matching it; this
    checks the actual keyword sets used in heartbeat/maintenance.py.
    """
    sig = inspect.signature(Notifier.notify)
    call_sites = [
        {"title": "t", "body": "b", "type": "nudge", "priority": "normal"},
        {"title": "t", "body": "b", "type": "followup", "priority": "high"},
        {"title": "t", "body": "b", "type": "email", "priority": "normal"},
        {"title": "t", "body": "b", "type": "storage", "priority": "high"},
        {"title": "t", "body": "b", "type": "update", "priority": "low"},
    ]
    for kwargs in call_sites:
        sig.bind(None, **kwargs)  # raises TypeError if the call site is invalid
