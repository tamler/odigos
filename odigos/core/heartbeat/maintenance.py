"""Maintenance functions for the heartbeat loop."""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.core.heartbeat.orchestrator import Heartbeat

logger = logging.getLogger(__name__)


async def run_evolution(hb: "Heartbeat") -> None:
    """Phase 5: Score past actions, manage trials, run strategist, rollup domain perf."""
    try:
        # evolution.enabled gates EVERYTHING in this phase, because every part
        # of it is LLM-driven self-modification:
        #   - trials/strategist: promotion writes LLM text into data/agent/*.md
        #   - consolidation: PromptConsolidator writes operational_rules.md and
        #     behavioral_principles.md into data/agent/ via self._llm.complete()
        #   - skill re-verification: LLM-scored, and demotes skills on failure
        # An earlier version of this gate excused the last two as "user-driven
        # features". That was wrong -- consolidation is grounded in user
        # corrections but the text it writes is LLM-generated, into the same
        # directory the charter is protecting.
        _evo = hb.settings.evolution if hb.settings else None
        _evo_enabled = bool(_evo.enabled) if _evo else False

        if _evo_enabled:
            scored = await hb.evolution_engine.score_past_actions(limit=3)
            if scored:
                logger.debug("Evolution: scored %d past actions", scored)

            result = await hb.evolution_engine.check_active_trial()
            if result and result != "continue":
                logger.info("Evolution: trial %s", result)

            # Domain performance rollup (cheap, runs every evolution cycle)
            await hb.evolution_engine.rollup_domain_performance()

        # Consolidate corrections into prompt sections. Writes LLM-generated
        # text into data/agent/, so it obeys evolution.enabled too.
        if _evo_enabled and hasattr(hb, "consolidator") and hb.consolidator:
            try:
                stats = await hb.consolidator.consolidate()
                if stats.get("corrections_processed", 0) > 0:
                    logger.info(
                        "Consolidation: processed %d corrections, %d ops, %d knowledge skipped",
                        stats["corrections_processed"],
                        stats.get("operations", 0),
                        stats.get("knowledge_skipped", 0),
                    )
            except Exception:
                logger.debug("Consolidation failed", exc_info=True)

        # Re-verify one skill per cycle if score diverges. LLM-scored and can
        # demote a skill, so it obeys evolution.enabled too.
        if _evo_enabled and hasattr(hb, "skill_verifier") and hb.skill_verifier and hasattr(hb, "skill_registry") and hb.skill_registry:
            try:
                await _reverify_one_skill(hb)
            except Exception:
                logger.debug("Skill re-verification failed", exc_info=True)

        # Run strategist if enough new evaluations. Gated: the strategist's whole
        # output is new trials, which is the thing evolution.enabled turns off.
        if _evo_enabled and hb.strategist:
            if await hb.strategist.should_run():
                analysis = await hb.strategist.analyze()
                if analysis:
                    logger.info("Strategist: analyzed, %d hypotheses",
                                len(analysis.get("hypotheses", [])))
    except Exception:
        logger.debug("Evolution cycle failed", exc_info=True)


async def _reverify_one_skill(hb) -> None:
    """Re-verify at most one committed/mature skill whose real-world score diverges."""
    from odigos.skills.maturity import demote_on_failed_verification

    for skill in hb.skill_registry.list():
        if skill.builtin or skill.maturity not in ("committed", "mature"):
            continue
        if not skill.verified or skill.verification_score == 0.0:
            continue
        if skill.avg_score < skill.verification_score - 0.15:
            logger.info(
                "Re-verifying skill '%s' (avg=%.2f vs vscore=%.2f)",
                skill.name, skill.avg_score, skill.verification_score,
            )
            skill.escalation_level += 1
            result = await hb.skill_verifier.verify_skill(skill.name)
            skill.verification_score = result.overall_score
            from datetime import datetime, timezone
            skill.verification_at = datetime.now(timezone.utc).isoformat()
            skill.verified = result.passed
            demotion = demote_on_failed_verification(skill)
            if demotion:
                skill.maturity = demotion
                skill.escalation_level = 0
            hb.skill_registry.save(skill.name)
            return  # max 1 per cycle


async def check_for_updates(hb: "Heartbeat") -> None:
    """Check for code updates and optionally apply them."""
    try:
        from odigos.core.updater import (
            apply_update,
            check_for_updates as _check_for_updates,
            restart_service,
        )

        update_cfg = hb.settings.auto_update
        info = await asyncio.to_thread(
            _check_for_updates, update_cfg.branch,
        )
        if not info:
            return

        logger.info(
            "Update available: %s -> %s (%d commits)",
            info["local"],
            info["remote"],
            info["commits"],
        )

        if update_cfg.auto_apply:
            success, msg = await asyncio.to_thread(
                apply_update, update_cfg.branch,
            )
            if success:
                logger.info(
                    "Update applied successfully, restarting...",
                )
                if hb.notifier:
                    await hb.notifier.notify(
                        title="Update Applied",
                        body=(
                            f"Applied {info['commits']} new "
                            f"commit(s). Restarting now."
                        ),
                        priority="normal",
                    )
                # Give notification time to deliver
                await asyncio.sleep(2)
                await asyncio.to_thread(restart_service)
            else:
                logger.error("Update failed: %s", msg)
                if hb.notifier:
                    await hb.notifier.notify(
                        title="Update Failed",
                        body=(
                            f"Auto-update failed: "
                            f"{msg[:200]}"
                        ),
                        priority="high",
                    )
        else:
            # Notify only
            if hb.notifier:
                await hb.notifier.notify(
                    title="Update Available",
                    body=(
                        f"{info['commits']} new commit(s) "
                        f"available. Latest: "
                        f"{info['log'][:200]}"
                    ),
                    priority="normal",
                )
    except Exception:
        logger.debug("Update check failed", exc_info=True)


async def check_storage_quota(hb: "Heartbeat") -> None:
    """Check data/ directory size against configured quota limits."""
    try:
        from pathlib import Path

        quota = hb.settings.storage if hb.settings else None
        warn_gb = quota.warn_gb if quota else 10.0
        cap_gb = quota.cap_gb if quota else 12.0

        data_dir = Path("data")
        if not data_dir.exists():
            return

        def _calc_size() -> int:
            return sum(
                f.stat(follow_symlinks=False).st_size
                for f in data_dir.rglob("*")
                if f.is_file() and not f.is_symlink()
            )

        total_bytes = await asyncio.to_thread(_calc_size)
        total_gb = total_bytes / (1024 ** 3)

        # Record usage BEFORE notifying. This write is what tools consult before
        # writing files, and it used to sit after the notify calls inside the
        # same try -- so any notify failure skipped it. notify() raised
        # TypeError on every call (the priority= bug), which meant the usage
        # figure was recorded only while under the warn threshold and went stale
        # exactly when it started to matter.
        await hb.db.execute(
            """INSERT OR REPLACE INTO kv (key, value) VALUES ('storage_usage_gb', ?)""",
            (f"{total_gb:.4f}",),
        )

        if total_gb >= cap_gb:
            logger.warning("Storage quota exceeded: %.2f GB / %.1f GB cap", total_gb, cap_gb)
            if hb.notifier:
                await hb.notifier.notify(
                    title="Storage Limit Reached",
                    body=(
                        f"Storage usage is {total_gb:.1f} GB, exceeding the "
                        f"{cap_gb:.0f} GB limit. File uploads and image generation "
                        f"may be blocked until space is freed."
                    ),
                    priority="high",
                )
        elif total_gb >= warn_gb:
            logger.info("Storage warning: %.2f GB / %.1f GB warn threshold", total_gb, warn_gb)
            if hb.notifier:
                await hb.notifier.notify(
                    title="Storage Warning",
                    body=(
                        f"Storage usage is {total_gb:.1f} GB, approaching the "
                        f"{cap_gb:.0f} GB limit. Consider cleaning up old files."
                    ),
                    priority="normal",
                )

    except Exception:
        logger.debug("Storage quota check failed", exc_info=True)


async def check_email(hb: "Heartbeat") -> bool:
    """Check inbox for new emails and notify the user."""
    try:
        from odigos.tools.email import CheckEmailTool
        tool = CheckEmailTool(email_config=hb._email_config)
        result = await tool.execute({"limit": 5, "unread_only": True})
        if not result.success:
            return False
        if "No new emails" in result.data:
            return False

        # Notify user about new emails
        if hb.notifier:
            # Count emails from the result
            email_count = result.data.count("From:")
            if email_count > 0:
                await hb.notifier.notify(
                    title="New Email",
                    body=f"You have {email_count} new email(s). Ask me to read them.",
                    priority="normal",
                )
                logger.info("Email check: %d new message(s)", email_count)
                return True
    except Exception:
        logger.debug("Email check failed", exc_info=True)
    return False


async def send_nudges(hb: "Heartbeat") -> bool:
    """Check for stale tasks and overdue goals, notify user."""
    try:
        from odigos.core.nudger import (
            format_nudge_notification,
            get_nudge_items,
        )

        nudges = await get_nudge_items(hb.db)
        if not nudges:
            return False

        msg = format_nudge_notification(nudges)
        if msg and hb.notifier:
            await hb.notifier.notify(
                title="Reminder",
                body=msg,
                priority="normal",
            )
            return True
    except Exception:
        logger.debug("Nudge check failed", exc_info=True)
    return False


async def check_followups(hb: "Heartbeat") -> bool:
    """Check for user commitments that might need follow-up."""
    try:
        from odigos.core.followups import (
            find_untracked_commitments,
            format_followup_notification,
        )
        commitments = await find_untracked_commitments(hb.db)
        if not commitments:
            return False
        msg = format_followup_notification(commitments)
        if msg and hb.notifier:
            await hb.notifier.notify(
                title="Follow-up",
                body=msg,
                priority="low",
            )
            return True
    except Exception:
        logger.debug(
            "Follow-up check failed", exc_info=True,
        )
    return False


