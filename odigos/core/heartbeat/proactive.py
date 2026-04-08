"""Proactive agent pipeline — scan → prioritize → execute → publish.

Replaces idle_think. Runs when the heartbeat is idle and budget allows.
Stages 1-2 (scan+prioritize) run synchronously in the tick.
Stages 3-4 (execute+publish) run as an async background task.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.core.heartbeat.orchestrator import Heartbeat

logger = logging.getLogger(__name__)


@dataclass
class Opportunity:
    source: str
    title: str
    context: str
    priority_hint: float = 0.5
    conversation_id: str | None = None


# --- Stage 1: Signal Sources ---

async def scan_brain_gaps(hb: Heartbeat) -> list[Opportunity]:
    """Find entities with no summary, facts with no cross-references."""
    opportunities = []
    if not hb.db:
        return opportunities
    # Entities with no summary
    rows = await hb.db.fetch_all(
        "SELECT name, type FROM entities WHERE status = 'active' "
        "AND (summary IS NULL OR summary = '') LIMIT 5"
    )
    for r in rows:
        opportunities.append(Opportunity(
            source="brain_gaps",
            title=f"Research {r['name']}",
            context=f"Entity '{r['name']}' ({r['type']}) has no summary",
            priority_hint=0.5,
        ))
    return opportunities


async def scan_recent_conversations(hb: Heartbeat) -> list[Opportunity]:
    """Find topics from last 24h that weren't fully explored."""
    opportunities = []
    if not hb.db:
        return opportunities
    rows = await hb.db.fetch_all(
        "SELECT c.id, c.title, m.content FROM conversations c "
        "JOIN messages m ON m.conversation_id = c.id "
        "WHERE m.role = 'user' AND m.created_at > datetime('now', '-1 day') "
        "AND length(m.content) > 50 "
        "ORDER BY m.created_at DESC LIMIT 10"
    )
    for r in rows:
        opportunities.append(Opportunity(
            source="recent_conversations",
            title=f"Explore: {r['content'][:60]}",
            context=f"User asked about this in conversation {r['id'][:8]}",
            priority_hint=0.4,
            conversation_id=r["id"],
        ))
    return opportunities


async def scan_active_goals(hb: Heartbeat) -> list[Opportunity]:
    """Check active goals for progress opportunities."""
    opportunities = []
    if not hb.goal_store:
        return opportunities
    goals = await hb.goal_store.list_goals(status="active")
    for g in goals:
        opportunities.append(Opportunity(
            source="active_goals",
            title=f"Progress on: {g['description'][:60]}",
            context=f"Goal {g['id'][:8]}: {g.get('progress_note', 'no progress noted')}",
            priority_hint=0.6,
        ))
    return opportunities


async def scan_synthesis_opportunities(hb: Heartbeat) -> list[Opportunity]:
    """Find opportunities to synthesize across accumulated knowledge.

    Looks for entity pairs connected through shared relationships and
    topics that recur across multiple conversations.
    """
    opportunities = []
    if not hb.db:
        return opportunities

    # Entity pairs connected through shared relationship targets
    try:
        pairs = await hb.db.fetch_all(
            "SELECT DISTINCT e1.name as name1, e1.type as type1, "
            "e2.name as name2, e2.type as type2 "
            "FROM edges a "
            "JOIN edges b ON a.target_id = b.target_id AND a.source_id != b.source_id "
            "JOIN entities e1 ON a.source_id = e1.id "
            "JOIN entities e2 ON b.source_id = e2.id "
            "WHERE e1.status = 'active' AND e2.status = 'active' "
            "LIMIT 5"
        )
        for p in pairs:
            opportunities.append(Opportunity(
                source="synthesis",
                title=f"Connection: {p['name1']} and {p['name2']}",
                context=f"{p['name1']} ({p['type1']}) and {p['name2']} ({p['type2']}) "
                        f"share a common relationship — worth exploring",
                priority_hint=0.3,
            ))
    except Exception:
        pass

    # Topics recurring across multiple conversations in the last 7 days
    try:
        repeated = await hb.db.fetch_all(
            "SELECT substr(content, 1, 50) as topic, "
            "COUNT(DISTINCT conversation_id) as conv_count "
            "FROM messages WHERE role = 'user' "
            "AND created_at > datetime('now', '-7 days') "
            "AND length(content) > 30 "
            "GROUP BY topic HAVING conv_count >= 2 LIMIT 3"
        )
        for r in repeated:
            opportunities.append(Opportunity(
                source="synthesis",
                title=f"Recurring topic: {r['topic']}",
                context=f"Appeared in {r['conv_count']} conversations — may warrant synthesis",
                priority_hint=0.35,
            ))
    except Exception:
        pass

    return opportunities


SIGNAL_SOURCES = [
    scan_brain_gaps,
    scan_recent_conversations,
    scan_active_goals,
    scan_synthesis_opportunities,
]


# --- Stage 2: Prioritize ---

async def prioritize(
    hb: Heartbeat,
    opportunities: list[Opportunity],
    diary_context: str = "",
) -> Opportunity | None:
    """Filter and rank opportunities. Returns top 1 or None."""
    if not opportunities:
        return None

    # Filter out topics user thumbs-downed
    if hb.db:
        suppressed = await hb.db.fetch_all(
            "SELECT source FROM notifications WHERE reaction = 'not_relevant' "
            "GROUP BY source HAVING SUM(CASE WHEN reaction='thumbs_up' THEN 1 "
            "WHEN reaction='not_relevant' THEN -1 ELSE 0 END) < -2"
        )
        suppressed_sources = {r["source"] for r in suppressed}
        opportunities = [o for o in opportunities if o.source not in suppressed_sources]

    if not opportunities:
        return None

    # If 3 or fewer, just take the highest priority_hint
    if len(opportunities) <= 3:
        return max(opportunities, key=lambda o: o.priority_hint)

    # More than 3: use a cheap LLM call to rank
    try:
        from odigos.core.llm_prompt import call_llm
        opp_text = "\n".join(
            f"{i+1}. [{o.source}] {o.title}: {o.context}"
            for i, o in enumerate(opportunities[:10])
        )
        prompt = (
            "Rank these opportunities by value to the user. "
            "Return the number of the most valuable one.\n\n"
            f"{opp_text}\n\n"
            f"Recent agent diary:\n{diary_context[:500]}\n\n"
            "Reply with just the number."
        )
        resp = await call_llm(
            hb.provider, [{"role": "user", "content": prompt}],
            max_tokens=10, temperature=0.1,
            model=getattr(hb, "_background_model", None),
        )
        if resp and resp.content.strip().isdigit():
            idx = int(resp.content.strip()) - 1
            if 0 <= idx < len(opportunities):
                return opportunities[idx]
    except Exception:
        logger.debug("Proactive prioritize LLM call failed, using hint score")

    return max(opportunities, key=lambda o: o.priority_hint)


# --- Stage 3+4: Execute + Publish (async background task) ---

async def _execute_and_publish(hb: Heartbeat, opportunity: Opportunity) -> None:
    """Execute the opportunity and publish results. Runs as background task."""
    from odigos.channels.base import UniversalMessage
    from odigos.memory.brain_writer import BrainWriter
    from datetime import datetime, timezone
    import uuid

    try:
        # Build message for headless execution
        msg = UniversalMessage(
            id=uuid.uuid4().hex,
            channel="proactive",
            sender="system",
            content=(
                f"Research and provide findings on: {opportunity.title}\n\n"
                f"Context: {opportunity.context}"
            ),
            timestamp=datetime.now(timezone.utc),
            metadata={"conversation_id": opportunity.conversation_id or ""},
        )

        # Execute via headless agent
        result = await hb.agent.handle_message(
            msg, headless=True,
            background_model=getattr(hb, "_background_model", ""),
        )

        if not result or len(result.strip()) < 20:
            logger.info(
                "Proactive execution produced no useful result for: %s",
                opportunity.title,
            )
            return

        # Quality threshold — reject low-quality results
        result_text = result.strip()
        low_quality_markers = [
            "i don't know", "i cannot", "i'm not sure", "i am not sure",
            "i don't have enough", "no information available",
            "i was unable to find", "i couldn't find",
        ]
        result_lower = result_text.lower()
        if any(marker in result_lower for marker in low_quality_markers):
            logger.info("Proactive result below quality threshold: %s", opportunity.title)
            return
        if len(result_text) < 100:
            logger.info("Proactive result too short (%d chars): %s", len(result_text), opportunity.title)
            return

        # Publish via BrainWriter
        writer = BrainWriter()
        artifact_path = await writer.write_synthesis(
            title=opportunity.title,
            content=result,
            source=opportunity.source,
            source_context=opportunity.context,
            conversation_id=opportunity.conversation_id,
        )

        # Write diary entry
        await writer.append_diary(
            summary=(
                f"Researched: {opportunity.title}. "
                f"Produced synthesis at {artifact_path}."
            ),
            open_threads="",
        )

        # Notify user
        if hb.notifier:
            await hb.notifier.notify(
                title=opportunity.title,
                body=result[:200],
                type="finding",
                artifact_path=artifact_path,
                conversation_id=opportunity.conversation_id,
                source=opportunity.source,
            )

        logger.info(
            "Proactive cycle complete: %s -> %s",
            opportunity.title, artifact_path,
        )

    except Exception:
        logger.exception(
            "Proactive execute/publish failed for: %s", opportunity.title,
        )


# --- Main entry point ---

async def run_proactive(hb: Heartbeat) -> None:
    """Run the proactive pipeline. Called from heartbeat Phase 5."""
    # Check config
    proactive_config = getattr(hb, "_proactive_config", None)
    if proactive_config and not proactive_config.enabled:
        return

    # Rate limit
    now = time.monotonic()
    interval = proactive_config.interval_seconds if proactive_config else 900
    if now - hb._last_idle < interval:
        return
    hb._last_idle = now

    # Stage 1: Scan
    all_opportunities: list[Opportunity] = []
    results = await asyncio.gather(
        *[source(hb) for source in SIGNAL_SOURCES],
        return_exceptions=True,
    )
    for result in results:
        if isinstance(result, list):
            all_opportunities.extend(result)

    if not all_opportunities:
        return

    # Read diary for context
    diary_context = ""
    from pathlib import Path
    diary_path = Path("data/agent/diary.md")
    if diary_path.exists():
        lines = diary_path.read_text(encoding="utf-8").split("\n")
        diary_context = "\n".join(lines[-30:])  # Last ~5 entries

    # Stage 2: Prioritize
    selected = await prioritize(hb, all_opportunities, diary_context)
    if not selected:
        return

    logger.info(
        "Proactive: selected '%s' from %d opportunities",
        selected.title, len(all_opportunities),
    )

    # Stages 3+4: Execute + Publish (async, doesn't block tick)
    asyncio.create_task(_execute_and_publish(hb, selected))
