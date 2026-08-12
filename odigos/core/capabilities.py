"""Registry of capabilities that failed to load, and the shared TextBlob probe.

Charter 01-cleanup.md §0f. The rule this module exists to enforce:

    A dependency declared in pyproject.toml failing to import is an ERROR,
    not a feature flag.

The failure mode it prevents is the one in anti-patterns.md -- a feature that
reads as present and isn't. `except ImportError: _X_AVAILABLE = False` turns a
broken install into a silently disabled feature: no log line, no health signal,
and the only symptom is a 404 or a quietly skipped code path. WebAuthn sat
broken behind exactly that guard, and the only reason anyone noticed was that
four tests failed.

Guarded imports call `record_degraded()` so the failure is logged once at ERROR
and stays visible via `degraded_capabilities()`, which /api/state reports.

Genuinely optional imports -- ones with no entry in pyproject.toml -- pass
`declared=False` and log at debug instead. Today `python-dotenv` is the only one.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_degraded: dict[str, str] = {}


def record_degraded(capability: str, exc: BaseException, *, declared: bool = True) -> None:
    """Record that `capability` is unavailable because its import failed."""
    detail = f"{type(exc).__name__}: {exc}"
    _degraded[capability] = detail
    if declared:
        logger.error(
            "Capability %r is unavailable: %s is declared in pyproject.toml but failed "
            "to import (%s). This is a broken install, not a disabled feature.",
            capability,
            capability,
            detail,
        )
    else:
        logger.debug("Optional capability %r unavailable: %s", capability, detail)


def degraded_capabilities() -> dict[str, str]:
    """Capability name -> the import error that disabled it. Empty is healthy."""
    return dict(_degraded)


# --- shared TextBlob probe -------------------------------------------------
# classifier, evaluator, content_filter, followups and template_index each had
# their own identical try/except. One probe means one log line instead of five,
# and one place to look. Callers keep checking `TextBlob is None`.
#
# Note that `TextBlob is not None` is necessary but not sufficient: TextBlob
# raises LookupError at call time when its NLTK corpora are absent, which the
# call sites already handle separately.
try:
    from textblob import TextBlob
except ImportError as _e:  # pragma: no cover - exercised only on a broken install
    TextBlob = None  # type: ignore[assignment,misc]
    record_degraded("textblob", _e)

__all__ = ["TextBlob", "degraded_capabilities", "record_degraded"]
