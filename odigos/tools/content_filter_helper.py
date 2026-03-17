"""Shared helper for applying ContentFilter to tool output."""
from __future__ import annotations

import logging

from odigos.core.content_filter import ContentFilter
from odigos.tools.base import ToolResult

logger = logging.getLogger(__name__)

_content_filter = ContentFilter()


def filter_external_content(raw_output: str, source_label: str) -> ToolResult:
    """Scan raw_output through the content filter and return an appropriate ToolResult.

    If the content filter flags the output as medium or high risk, the sanitized
    text (with injection warnings) is returned instead of the raw output.
    """
    result = _content_filter.scan(raw_output)
    if result.risk_level == "high":
        logger.warning(
            "Content filter: HIGH risk from %s -- patterns: %s",
            source_label, result.matched_patterns,
        )
        return ToolResult(success=True, data=result.sanitized_text)
    if result.risk_level == "medium":
        logger.info(
            "Content filter: MEDIUM risk from %s -- patterns: %s",
            source_label, result.matched_patterns,
        )
        return ToolResult(success=True, data=result.sanitized_text)

    return ToolResult(success=True, data=raw_output)
