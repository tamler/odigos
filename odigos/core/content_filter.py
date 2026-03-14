"""Content filter for detecting prompt injection in external content.

Heuristic regex-based scanner that flags common prompt injection patterns
before external content (web pages, RSS feeds) reaches the LLM context.
"""
from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ContentFilterResult:
    is_suspicious: bool
    risk_level: str  # "low", "medium", "high"
    matched_patterns: list[str] = field(default_factory=list)
    sanitized_text: str = ""


# Each entry: (compiled regex, human-readable label)
_INJECTION_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Instruction override
    (re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE), "ignore previous instructions"),
    (re.compile(r"disregard\s+(all\s+)?previous", re.IGNORECASE), "disregard previous"),
    # Role hijacking
    (re.compile(r"you\s+are\s+now\b", re.IGNORECASE), "you are now"),
    (re.compile(r"act\s+as\b", re.IGNORECASE), "act as"),
    (re.compile(r"pretend\s+to\s+be\b", re.IGNORECASE), "pretend to be"),
    (re.compile(r"your\s+new\s+role\b", re.IGNORECASE), "your new role"),
    # Prompt exfiltration
    (re.compile(r"system\s+prompt", re.IGNORECASE), "system prompt"),
    (re.compile(r"reveal\s+your\s+prompt", re.IGNORECASE), "reveal your prompt"),
    (re.compile(r"show\s+your\s+instructions", re.IGNORECASE), "show your instructions"),
    # Model-specific tokens
    (re.compile(r"\[INST\]", re.IGNORECASE), "[INST] token"),
    (re.compile(r"<<SYS>>", re.IGNORECASE), "<<SYS>> token"),
    (re.compile(r"</s>"), "</s> token"),
    (re.compile(r"<\|im_start\|>"), "<|im_start|> token"),
    # Rule bypass
    (re.compile(r"do\s+not\s+follow\s+(your\s+)?(instructions|rules|guidelines)", re.IGNORECASE), "do not follow instructions"),
    (re.compile(r"override\s+(your\s+)?(instructions|rules|guidelines)", re.IGNORECASE), "override instructions"),
    (re.compile(r"bypass\s+(your\s+)?(instructions|rules|guidelines)", re.IGNORECASE), "bypass instructions"),
]

# Common injection phrases to check for in base64-encoded form
_BASE64_PROBES = [
    "ignore previous instructions",
    "you are now",
    "system prompt",
]


def _check_base64(text: str) -> list[str]:
    """Scan for base64-encoded injection payloads embedded in text."""
    matches = []
    # Find base64-looking segments (at least 20 chars of valid base64)
    for b64_match in re.finditer(r"[A-Za-z0-9+/]{20,}={0,2}", text):
        segment = b64_match.group()
        try:
            decoded = base64.b64decode(segment).decode("utf-8", errors="ignore").lower()
        except Exception:
            continue
        for probe in _BASE64_PROBES:
            if probe in decoded:
                matches.append(f"base64-encoded: {probe}")
    return matches


def _determine_risk(pattern_count: int) -> str:
    if pattern_count == 0:
        return "low"
    if pattern_count <= 2:
        return "medium"
    return "high"


class ContentFilter:
    """Scans text for common prompt injection patterns."""

    def scan(self, text: str) -> ContentFilterResult:
        if not text:
            return ContentFilterResult(
                is_suspicious=False,
                risk_level="low",
                matched_patterns=[],
                sanitized_text=text,
            )

        matched: list[str] = []

        for pattern, label in _INJECTION_PATTERNS:
            if pattern.search(text):
                matched.append(label)

        matched.extend(_check_base64(text))

        # Deduplicate while preserving order
        seen: set[str] = set()
        unique_matched: list[str] = []
        for m in matched:
            if m not in seen:
                seen.add(m)
                unique_matched.append(m)

        risk_level = _determine_risk(len(unique_matched))
        is_suspicious = len(unique_matched) > 0

        if is_suspicious:
            pattern_list = ", ".join(unique_matched)
            sanitized = (
                f"[EXTERNAL CONTENT - POSSIBLE INJECTION DETECTED: {pattern_list}] {text}"
            )
        else:
            sanitized = text

        return ContentFilterResult(
            is_suspicious=is_suspicious,
            risk_level=risk_level,
            matched_patterns=unique_matched,
            sanitized_text=sanitized,
        )
