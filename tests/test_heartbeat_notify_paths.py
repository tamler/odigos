"""The heartbeat paths that call Notifier.notify(priority=) -- for real.

Charter 01-cleanup.md §1. Every one of these raised TypeError into an
`except Exception: logger.debug` because notify() had no `priority` keyword, so
nudges, follow-ups and storage warnings never fired on any agent.

Why this file exists rather than the charter's suggested fix:

The charter says to delete the mocks in test_heartbeat_announce.py that hide the
bug. Deleting them would not have caught it. Those tick tests run against an
empty database, so get_nudge_items() and find_untracked_commitments() return
nothing and the code returns before ever reaching notify(). The mocks are also
legitimate isolation for a test about announce behaviour.

What was actually missing is any test that reaches the notify() call at all --
send_nudges and check_followups were mocked in all three tick tests and
exercised for real in none. These stub the data source and use a REAL Notifier,
so the call signature is genuinely exercised.
"""
from types import SimpleNamespace

import pytest

from odigos.core.heartbeat import maintenance
from odigos.core.notifier import Notifier


class _Registry:
    """Channel registry that records what each channel was asked to send."""

    def __init__(self):
        self.sent = []

    def all(self):
        registry = self

        class _Channel:
            channel_name = "recorder"

            async def notify(self, *, title, body, conversation_id=None):
                registry.sent.append((title, body))

        return [_Channel()]

    def get(self, name):
        return None


def _hb(notifier):
    return SimpleNamespace(db=None, notifier=notifier, settings=None)


async def test_send_nudges_reaches_notify_and_reports_work(monkeypatch):
    import odigos.core.nudger as nudger

    monkeypatch.setattr(
        nudger, "get_nudge_items", lambda db: _async([{"kind": "stale"}])
    )
    monkeypatch.setattr(nudger, "format_nudge_notification", lambda items: "2 stale tasks")

    registry = _Registry()
    did_work = await maintenance.send_nudges(_hb(Notifier(db=None, channel_registry=registry)))

    assert did_work is True, (
        "send_nudges swallowed a TypeError from notify(priority=) and reported "
        "no work -- the exact silent failure this bug produced"
    )
    assert registry.sent == [("Reminder", "2 stale tasks")]


async def test_check_followups_reaches_notify_and_reports_work(monkeypatch):
    import odigos.core.followups as followups

    monkeypatch.setattr(
        followups, "find_untracked_commitments", lambda db: _async([{"text": "call bob"}])
    )
    monkeypatch.setattr(
        followups, "format_followup_notification", lambda items: "1 open commitment"
    )

    registry = _Registry()
    did_work = await maintenance.check_followups(
        _hb(Notifier(db=None, channel_registry=registry))
    )

    assert did_work is True
    assert registry.sent == [("Follow-up", "1 open commitment")]


@pytest.mark.parametrize(
    "func,attr",
    [("send_nudges", "get_nudge_items"), ("check_followups", "find_untracked_commitments")],
)
async def test_notify_failures_are_not_reported_as_work(func, attr, monkeypatch):
    """If notify genuinely fails, the phase must report False, not True."""
    mod = "odigos.core.nudger" if func == "send_nudges" else "odigos.core.followups"
    import importlib

    m = importlib.import_module(mod)
    monkeypatch.setattr(m, attr, lambda db: _async([{"x": 1}]))
    fmt = "format_nudge_notification" if func == "send_nudges" else "format_followup_notification"
    monkeypatch.setattr(m, fmt, lambda items: "msg")

    class _Exploding:
        async def notify(self, **kwargs):
            raise RuntimeError("channel down")

    assert await getattr(maintenance, func)(_hb(_Exploding())) is False


async def _async(value):
    return value


async def test_nudges_do_not_suppress_the_llm_phases(monkeypatch):
    """A nudge costs no LLM budget and must not trip the did_work gate.

    Charter §1 starvation item. Until notify() accepted priority=, send_nudges
    always returned False and never tripped the gate; repairing it would have
    started starving proactive/evolution/memory-evolution for the first time.
    """
    import inspect

    from odigos.core.heartbeat import orchestrator

    src = inspect.getsource(orchestrator)
    assert "did_work |= await maintenance.send_nudges" not in src, (
        "send_nudges feeds did_work again; a no-LLM notification would suppress "
        "plan execution, proactive, evolution and memory evolution for that tick"
    )
    assert "did_work |= await maintenance.check_followups" not in src, (
        "check_followups feeds did_work again -- same starvation problem"
    )
    assert "await maintenance.send_nudges(self)" in src, "phase 4c must still run"
    assert "await maintenance.check_followups(self)" in src, "phase 4d must still run"
