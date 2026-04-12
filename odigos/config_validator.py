"""Startup config validation for common misconfigurations."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.config import Settings

VALID_STT_PROVIDERS = {"groq", "local", "disabled"}
VALID_TTS_PROVIDERS = {"edge", "local", "disabled"}


def validate_settings(settings: Settings) -> list[str]:
    """Return warning messages for common misconfigurations.

    Never raises -- always returns a (possibly empty) list of strings.
    """
    warnings: list[str] = []

    # LLM configuration
    if not settings.llm_api_key:
        warnings.append(
            "llm_api_key is empty -- LLM calls will fail."
        )
    if not settings.llm.base_url:
        warnings.append(
            "llm.base_url is empty -- LLM calls will fail."
        )

    # Budget sanity
    if settings.budget.daily_limit_usd <= 0:
        warnings.append(
            "budget.daily_limit_usd is <= 0."
        )
    if settings.budget.monthly_limit_usd <= 0:
        warnings.append(
            "budget.monthly_limit_usd is <= 0."
        )

    # Budget cost tracking: warn if using safety-net defaults
    has_budget = settings.budget.daily_limit_usd > 0 or settings.budget.monthly_limit_usd > 0
    has_cost_rate = (
        settings.llm.cost_per_million_tokens > 0
        or settings.llm.cost_per_million_input > 0
        or settings.llm.cost_per_million_output > 0
    )
    if has_budget and not has_cost_rate:
        warnings.append(
            "llm.cost_per_million_input/output not configured -- using "
            "safety-net defaults ($1/$3 per million). Set explicit rates "
            "in config.yaml for accurate cost tracking."
        )
    if (
        settings.budget.daily_limit_usd
        > settings.budget.monthly_limit_usd
        and settings.budget.monthly_limit_usd > 0
    ):
        warnings.append(
            "budget.daily_limit_usd exceeds "
            "monthly_limit_usd."
        )

    # Voice / STT / TTS providers
    stt = settings.voice.stt_provider
    if stt not in VALID_STT_PROVIDERS:
        warnings.append(
            f"voice.stt_provider '{stt}' is not valid. "
            f"Expected one of {sorted(VALID_STT_PROVIDERS)}."
        )
    if stt == "groq" and not settings.service_key("groq"):
        warnings.append(
            "voice.stt_provider is 'groq' but "
            "services.groq is not set."
        )

    tts = settings.voice.tts_provider
    if tts not in VALID_TTS_PROVIDERS:
        warnings.append(
            f"voice.tts_provider '{tts}' is not valid. "
            f"Expected one of {sorted(VALID_TTS_PROVIDERS)}."
        )

    # Database directory
    db_dir = Path(settings.database.path).parent
    if not db_dir.exists():
        warnings.append(
            f"Database directory '{db_dir}' does not "
            "exist."
        )

    # Email (auto-enabled when imap_host is set — check other required fields)
    if settings.email.imap_host:
        missing = []
        if not settings.email.smtp_host:
            missing.append("smtp_host")
        if not settings.email.address:
            missing.append("address")
        if missing:
            warnings.append(
                "Email imap_host is configured but missing: "
                f"{', '.join(missing)}."
            )

    # Auto-update interval
    if settings.auto_update.check_interval_ticks < 10:
        warnings.append(
            "auto_update.check_interval_ticks is < 10 "
            "-- updates will check too frequently."
        )

    # Heartbeat interval
    if settings.heartbeat.interval_seconds < 5:
        warnings.append(
            "heartbeat.interval_seconds is < 5 "
            "-- this may cause excessive load."
        )

    # Mesh with no peers
    if settings.mesh.enabled and not settings.peers:
        warnings.append(
            "Mesh is enabled but no peers are "
            "configured."
        )

    # Approval disabled
    if not settings.approval.enabled:
        warnings.append(
            "approval.enabled is false -- code execution "
            "will proceed without confirmation."
        )

    return warnings
