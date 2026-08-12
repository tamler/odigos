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

# tools/catalog.py walks optional plugin modules and already distinguishes
# "third-party dep absent, skip this plugin" from "the module itself is broken",
# which is the distinction this rule exists to enforce. See its except clauses.
EXEMPT = {"catalog.py"}

# Names that mean "an import failed". ModuleNotFoundError subclasses ImportError,
# so catching it is the same pattern and must obey the same rule.
_IMPORT_ERROR_NAMES = {"ImportError", "ModuleNotFoundError"}


def _caught_names(node: ast.ExceptHandler) -> set[str]:
    """Exception names a handler catches, including dotted and aliased forms."""
    if node.type is None:
        return {"BareExcept"}
    exprs = node.type.elts if isinstance(node.type, ast.Tuple) else [node.type]
    names = set()
    for e in exprs:
        if isinstance(e, ast.Name):
            names.add(e.id)
        elif isinstance(e, ast.Attribute):
            names.add(e.attr)
    return names


def _except_import_handlers(path: Path):
    """Yield ExceptHandler nodes catching ImportError/ModuleNotFoundError."""
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ExceptHandler) and _caught_names(node) & _IMPORT_ERROR_NAMES:
            yield node


def _records_degradation(handler: ast.ExceptHandler) -> bool:
    """True only if the handler actually calls record_degraded()."""
    for node in ast.walk(handler):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id == "record_degraded":
                return True
            if isinstance(fn, ast.Attribute) and fn.attr == "record_degraded":
                return True
    return False


def test_every_importerror_handler_records_degradation():
    """`except ImportError` must call record_degraded() -- nothing weaker.

    An earlier version of this test accepted any log call or any non-None
    return. Adversarial review pointed out that a .debug() line defeats it,
    which is the exact pattern being outlawed: knowledge.py and webpush.py both
    logged at debug and were still invisible in practice. Returning a ToolResult
    to the caller is good and stays, but it tells the LLM, not the operator.
    """
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        if path.name in EXEMPT:
            continue
        for handler in _except_import_handlers(path):
            if not _records_degradation(handler):
                offenders.append(f"{path.relative_to(SRC.parent)}:{handler.lineno}")
    assert not offenders, (
        "these except-ImportError handlers do not call record_degraded(), so a "
        "declared dependency failing to import is invisible to an operator: "
        + ", ".join(offenders)
    )


def test_importerror_is_not_paired_with_broad_exception():
    """`except (ImportError, Exception)` is just `except Exception`.

    webpush.py had exactly this: the ImportError arm never applied and a missing
    declared dependency surfaced as a generic warning.
    """
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.ExceptHandler):
                continue
            names = _caught_names(node)
            if names & _IMPORT_ERROR_NAMES and {"Exception", "BaseException"} & names:
                offenders.append(f"{path.relative_to(SRC.parent)}:{node.lineno}")
    assert not offenders, (
        "ImportError paired with Exception in one handler is subsumed by it: "
        + ", ".join(offenders)
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
