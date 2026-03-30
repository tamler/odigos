"""Failure taxonomy for tool execution errors.

Classifies errors into categories with per-category recovery strategies.
Tools can pre-classify via ToolResult.failure_category, or the executor
calls classify() to determine the category from error text/exceptions.
"""
from __future__ import annotations

import re

TRANSIENT_PATTERNS = [
    re.compile(r"timeout|timed?\s*out", re.IGNORECASE),
    re.compile(r"rate.?limit|\b429\b|too many requests", re.IGNORECASE),
    re.compile(r"connection.?(reset|refused|error|closed)", re.IGNORECASE),
    re.compile(r"\b503\b|service unavailable|temporarily unavailable", re.IGNORECASE),
    re.compile(r"\b502\b|bad gateway", re.IGNORECASE),
    re.compile(r"ECONNRESET|ETIMEDOUT|ECONNREFUSED", re.IGNORECASE),
    re.compile(r"server error|internal server error|\b500\b", re.IGNORECASE),
]

INPUT_PATTERNS = [
    re.compile(r"missing\s+(required\s+)?param", re.IGNORECASE),
    re.compile(r"invalid\s+(input|param|argument|value)", re.IGNORECASE),
    re.compile(r"validation\s+(error|fail)", re.IGNORECASE),
    re.compile(r"\b400\b|bad request", re.IGNORECASE),
    re.compile(r"no\s+\w+\s+provided", re.IGNORECASE),
    re.compile(r"must\s+be\s+a\s+", re.IGNORECASE),
]

PERMISSION_PATTERNS = [
    re.compile(r"permission\s+denied|access\s+denied", re.IGNORECASE),
    re.compile(r"\b401\b|unauthorized|\b403\b|forbidden", re.IGNORECASE),
    re.compile(r"not\s+allowed|not\s+authorized", re.IGNORECASE),
    re.compile(r"approval.?(denied|rejected|required)", re.IGNORECASE),
    re.compile(r"path\s+outside\s+allowed", re.IGNORECASE),
]

UNAVAILABLE_PATTERNS = [
    re.compile(r"not\s+(configured|enabled|installed|available)", re.IGNORECASE),
    re.compile(r"no\s+provider|no\s+.*\s+available", re.IGNORECASE),
    re.compile(r"tool\s+not\s+found|unknown\s+tool", re.IGNORECASE),
    re.compile(r"feature\s+(disabled|not\s+enabled)", re.IGNORECASE),
]

TRANSIENT_EXCEPTIONS = (
    TimeoutError,
    ConnectionError,
    ConnectionResetError,
    ConnectionRefusedError,
    OSError,
)


def classify(error_msg: str | None = None, exception: Exception | None = None) -> str:
    """Classify a tool error into a failure category.

    Returns one of: transient, input, permission, unavailable, unknown.
    """
    if exception:
        if isinstance(exception, TRANSIENT_EXCEPTIONS):
            return "transient"

    text = error_msg or (str(exception) if exception else "")
    if not text:
        return "unknown"

    for pattern in PERMISSION_PATTERNS:
        if pattern.search(text):
            return "permission"

    for pattern in INPUT_PATTERNS:
        if pattern.search(text):
            return "input"

    for pattern in UNAVAILABLE_PATTERNS:
        if pattern.search(text):
            return "unavailable"

    for pattern in TRANSIENT_PATTERNS:
        if pattern.search(text):
            return "transient"

    return "unknown"


def should_retry(category: str, attempt: int, max_retries: dict[str, int]) -> bool:
    """Check if we should retry based on failure category and attempt count."""
    allowed = max_retries.get(category, 0)
    return attempt < allowed
