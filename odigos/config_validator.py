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

    # LLM configuration — providers, models, routing
    if not settings.providers:
        warnings.append(
            "No providers configured — add a `providers:` block to config.yaml."
        )
    if not settings.models:
        warnings.append(
            "No models configured — add a `models:` block to config.yaml."
        )
    for name, provider in settings.providers.items():
        if not provider.base_url:
            warnings.append(f"Provider '{name}' has no base_url.")
        # Local endpoints (Ollama, LM Studio, localhost) legitimately don't need keys.
        is_local = any(
            marker in provider.base_url.lower()
            for marker in ("localhost", "host.docker.internal", "127.0.0.1")
        )
        if not provider.api_key and not is_local:
            warnings.append(
                f"Provider '{name}' has no api_key — calls will fail. "
                "Use ${ENV_VAR} to pull from .env."
            )
    for alias, model in settings.models.items():
        if model.provider not in settings.providers:
            warnings.append(
                f"Model '{alias}' references unknown provider '{model.provider}'."
            )
        if not model.id:
            warnings.append(f"Model '{alias}' has no id.")

    # Routing — `fast` is mandatory, others fall back to it
    if not settings.llm.fast:
        warnings.append(
            "llm.fast is empty — at least one routing tier is required."
        )
    else:
        for tier in ("fast", "smart", "background", "fallback"):
            alias = getattr(settings.llm, tier, "") or ""
            if alias and alias not in settings.models:
                warnings.append(
                    f"llm.{tier} references unknown model alias '{alias}'."
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

    # Cost tracking: warn when a budgeted model on a remote provider has no rates.
    # Local models (Ollama / LM Studio / localhost) are free by definition.
    has_budget = settings.budget.daily_limit_usd > 0 or settings.budget.monthly_limit_usd > 0
    if has_budget:
        for alias, model in settings.models.items():
            if model.cost_in_per_mtok > 0 or model.cost_out_per_mtok > 0:
                continue
            provider = settings.providers.get(model.provider)
            if provider:
                base = (provider.base_url or "").lower()
                if any(m in base for m in ("localhost", "host.docker.internal", "127.0.0.1")):
                    continue
            warnings.append(
                f"Model '{alias}' has no cost rates set — budget tracking "
                "will rely on provider-reported cost only."
            )
            break  # one warning is enough
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
