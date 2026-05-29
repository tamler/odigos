"""Shared dangerous-argument guard for subprocess tools."""
from __future__ import annotations

_DANGEROUS_SUBSTR = ("../", "..\\", "\x00", "\r", "\n", "`", "$(")
_DANGEROUS_FLAGS = ("--output", "-o", "--config")


class ArgGuardError(ValueError):
    pass


def reject_dangerous_args(args: list[str], *, reject_option_args: bool = False) -> None:
    for a in args:
        if any(s in a for s in _DANGEROUS_SUBSTR):
            raise ArgGuardError(f"Blocked dangerous argument: {a!r}")
        if a in _DANGEROUS_FLAGS or a.startswith("--config="):
            raise ArgGuardError(f"Blocked option: {a!r}")
        if reject_option_args and (a.startswith("-") or a.startswith("/")):
            raise ArgGuardError(f"Blocked option-style/absolute arg: {a!r}")
