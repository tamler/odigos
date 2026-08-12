"""Charter 01-cleanup.md §0f: a declared dependency failing to import is an error.

The failure this pins is anti-patterns.md's shape -- a feature that reads as
present and isn't. WebAuthn sat broken behind `except ImportError: _AVAILABLE =
False` with no log line and no health signal; the only reason anyone noticed was
four failing tests.
"""
import ast
import logging
from pathlib import Path

import pytest

from odigos.core.capabilities import (
    TextBlob,
    degraded_capabilities,
    record_degraded,
)

SRC = Path(__file__).parent.parent / "odigos"

# The only guarded import in the tree whose package is not declared in
# pyproject.toml. Absence is legitimate, so it is allowed to stay quiet.
UNDECLARED_EXEMPT = {"config.py"}

# Guards a plugin's optional third-party dependency and already distinguishes
# "module absent" from "module broken" -- see the comments at the except lines.
CATALOG_EXEMPT = {"catalog.py"}


def _except_import_handlers(path: Path):
    """Yield ast.ExceptHandler nodes that catch ImportError in `path`."""
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler) or node.type is None:
            continue
        names = []
        if isinstance(node.type, ast.Name):
            names = [node.type.id]
        elif isinstance(node.type, ast.Tuple):
            names = [e.id for e in node.type.elts if isinstance(e, ast.Name)]
        if "ImportError" in names:
            yield node


def _is_silent(handler: ast.ExceptHandler) -> bool:
    """True if the handler neither logs nor records the exception."""
    for node in ast.walk(handler):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id == "record_degraded":
                return False
            if isinstance(fn, ast.Attribute) and fn.attr in {
                "error", "warning", "exception", "debug", "info"
            }:
                return False
        # Handlers that return an error to the caller are the good pattern.
        if isinstance(node, ast.Return) and node.value is not None:
            return False
    return True


def test_no_silent_importerror_handlers():
    """No `except ImportError` may swallow the failure without a breadcrumb."""
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        if path.name in UNDECLARED_EXEMPT | CATALOG_EXEMPT:
            continue
        for handler in _except_import_handlers(path):
            if _is_silent(handler):
                offenders.append(f"{path.relative_to(SRC.parent)}:{handler.lineno}")
    assert not offenders, (
        "these except-ImportError handlers swallow the failure silently; "
        "call record_degraded() or return an error to the caller: " + ", ".join(offenders)
    )


def test_record_degraded_logs_declared_dependency_at_error(caplog):
    with caplog.at_level(logging.ERROR, logger="odigos.core.capabilities"):
        record_degraded("some-declared-pkg", ImportError("boom"))
    assert "some-declared-pkg" in caplog.text
    assert "broken install" in caplog.text
    assert degraded_capabilities()["some-declared-pkg"] == "ImportError: boom"


def test_record_degraded_keeps_undeclared_quiet(caplog):
    with caplog.at_level(logging.ERROR, logger="odigos.core.capabilities"):
        record_degraded("some-optional-pkg", ImportError("nope"), declared=False)
    assert "some-optional-pkg" not in caplog.text
    assert "some-optional-pkg" in degraded_capabilities()


def test_textblob_probe_is_shared():
    """The five former per-module guards now resolve to one object."""
    from odigos.core import (
        classifier,
        content_filter,
        evaluator,
        followups,
        profiler,
        template_index,
    )

    for mod in (classifier, evaluator, content_filter, followups, template_index, profiler):
        assert mod.TextBlob is TextBlob, f"{mod.__name__} has its own TextBlob"


def test_webauthn_availability_flag_is_honest():
    """_HAS_WEBAUTHN was always True even when passkey auth was broken."""
    import odigos.api.system as system

    assert not hasattr(system, "_HAS_WEBAUTHN"), (
        "_HAS_WEBAUTHN is back; it cannot fail because webauthn.py defines "
        "`router` before its guarded imports and swallows their ImportError"
    )


@pytest.mark.parametrize("module_name", ["odigos.providers.llm", "odigos.core.executor"])
def test_jsonschema_is_imported_unguarded(module_name):
    """Validation must not be skippable by a missing import."""
    import importlib

    mod = importlib.import_module(module_name)
    assert getattr(mod, "jsonschema", None) is not None
