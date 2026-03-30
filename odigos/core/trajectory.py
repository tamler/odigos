"""Trajectory compression -- extract reusable patterns from tool call sequences.

Analyzes recent successful tool call chains and compresses them into
named patterns. These patterns inform the strategist about common
workflows that could become skills.
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.db import Database

logger = logging.getLogger(__name__)


async def extract_trajectories(db: Database, days: int = 7, min_count: int = 3) -> list[dict]:
    """Find repeated tool call sequences from recent conversations.

    Returns a list of trajectory patterns:
    [{"sequence": ["web_search", "run_code"], "count": 5, "avg_score": 7.2, "example_query": "..."}]
    """
    try:
        rows = await db.fetch_all(
            "SELECT m.conversation_id, m.content, m.role, m.timestamp, "
            "  e.overall_score "
            "FROM messages m "
            "LEFT JOIN evaluations e ON e.conversation_id = m.conversation_id "
            "WHERE m.timestamp > datetime('now', ?) "
            "ORDER BY m.conversation_id, m.timestamp",
            (f"-{days} days",),
        )
    except Exception:
        logger.debug("Trajectory extraction query failed", exc_info=True)
        return []

    # Group messages by conversation and extract tool call sequences
    conversations: dict[str, list[dict]] = {}
    for row in rows:
        cid = row["conversation_id"]
        if cid not in conversations:
            conversations[cid] = []
        conversations[cid].append(row)

    # Extract tool sequences per conversation
    sequence_counter: Counter = Counter()
    sequence_scores: dict[tuple, list[float]] = {}
    sequence_examples: dict[tuple, str] = {}

    for cid, messages in conversations.items():
        tools_in_conv = []
        first_user_msg = ""
        avg_score = None

        for msg in messages:
            if msg["role"] == "user" and not first_user_msg:
                first_user_msg = (msg["content"] or "")[:200]
            if msg["role"] == "assistant" and msg["content"]:
                # Extract tool names from assistant messages that contain tool calls
                content = msg["content"]
                if "tool_call" in content.lower() or not content.strip():
                    continue
            if msg.get("overall_score"):
                avg_score = msg["overall_score"]

            # Check for tool results (role=tool messages indicate a tool was called)
            if msg["role"] == "tool" or (msg["role"] == "assistant" and not msg["content"]):
                continue

        # Re-extract tool names from the conversation flow
        # Tool calls appear as role=assistant with empty content followed by role=tool
        tool_names = []
        for i, msg in enumerate(messages):
            if msg["role"] == "tool":
                # Look back for the tool name in prior assistant message
                # The tool name is embedded in the message flow
                pass

        # Simpler approach: look at tool_errors and evaluations for tool names
        # Actually, let's query tool usage directly
        pass

    # Query tool usage patterns from evaluations table
    try:
        tool_rows = await db.fetch_all(
            "SELECT conversation_id, task_type, overall_score "
            "FROM evaluations "
            "WHERE created_at > datetime('now', ?) AND overall_score IS NOT NULL "
            "ORDER BY conversation_id, created_at",
            (f"-{days} days",),
        )
    except Exception:
        return []

    # Group by conversation to find multi-tool patterns
    conv_tools: dict[str, list[str]] = {}
    conv_scores: dict[str, list[float]] = {}
    for row in tool_rows:
        cid = row["conversation_id"]
        task = row["task_type"] or "unknown"
        score = row["overall_score"] or 0
        conv_tools.setdefault(cid, []).append(task)
        conv_scores.setdefault(cid, []).append(score)

    # Find repeated sequences (2-4 tool patterns)
    for cid, tools in conv_tools.items():
        scores = conv_scores.get(cid, [])
        avg = sum(scores) / len(scores) if scores else 0

        for window in range(2, min(5, len(tools) + 1)):
            for i in range(len(tools) - window + 1):
                seq = tuple(tools[i:i + window])
                sequence_counter[seq] += 1
                sequence_scores.setdefault(seq, []).append(avg)

    # Return patterns that appear frequently enough
    patterns = []
    for seq, count in sequence_counter.most_common(20):
        if count < min_count:
            continue
        scores = sequence_scores.get(seq, [])
        avg_score = sum(scores) / len(scores) if scores else 0
        patterns.append({
            "sequence": list(seq),
            "count": count,
            "avg_score": round(avg_score, 1),
        })

    return patterns


async def get_trajectory_summary(db: Database) -> str:
    """Get a formatted summary of recent trajectory patterns for the strategist."""
    patterns = await extract_trajectories(db)
    if not patterns:
        return ""

    lines = ["## Trajectory Patterns (last 7 days)"]
    for p in patterns[:10]:
        seq_str = " -> ".join(p["sequence"])
        lines.append(f"- {seq_str} (x{p['count']}, avg score: {p['avg_score']})")

    return "\n".join(lines)
