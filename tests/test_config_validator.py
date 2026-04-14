"""Tests for startup config validation."""

from odigos.config import Settings
from odigos.config_validator import validate_settings


def _settings(**overrides) -> Settings:
    """Build a Settings object with a minimal valid provider/model set."""
    defaults: dict = {
        "services": {"groq": "gsk-test-key"},
        "providers": {
            "openrouter": {
                "base_url": "https://openrouter.ai/api/v1",
                "api_key": "sk-test-key",
            },
        },
        "models": {
            "scout": {
                "provider": "openrouter",
                "id": "meta-llama/llama-4-scout",
                "cost_in_per_mtok": 0.08,
                "cost_out_per_mtok": 0.30,
            },
        },
        # Leave smart/background/fallback empty so they fall through to `fast`
        "llm": {"fast": "scout", "smart": "", "background": "", "fallback": ""},
    }
    defaults.update(overrides)
    return Settings(**defaults)


def test_valid_config_no_warnings(tmp_path):
    db_path = tmp_path / "odigos.db"
    s = _settings(database={"path": str(db_path)})
    warnings = validate_settings(s)
    assert warnings == []


def test_missing_provider_key():
    """A provider without an api_key surfaces a warning."""
    s = _settings(
        providers={
            "openrouter": {
                "base_url": "https://openrouter.ai/api/v1",
                "api_key": "",
            },
        },
    )
    warnings = validate_settings(s)
    assert any("api_key" in w for w in warnings)


def test_missing_providers_block():
    """No providers at all surfaces a warning."""
    s = Settings()
    warnings = validate_settings(s)
    assert any("providers" in w.lower() for w in warnings)


def test_negative_budget():
    s = _settings(
        budget={
            "daily_limit_usd": -1,
            "monthly_limit_usd": 20,
        }
    )
    warnings = validate_settings(s)
    assert any("daily_limit_usd" in w for w in warnings)


def test_daily_exceeds_monthly():
    s = _settings(
        budget={
            "daily_limit_usd": 50,
            "monthly_limit_usd": 20,
        }
    )
    warnings = validate_settings(s)
    assert any("exceeds" in w for w in warnings)


def test_groq_stt_no_key():
    s = _settings(
        services={},
        voice={"stt_provider": "groq"},
    )
    warnings = validate_settings(s)
    assert any("groq" in w.lower() for w in warnings)


def test_invalid_stt_provider():
    s = _settings(
        voice={"stt_provider": "whisperx"},
    )
    warnings = validate_settings(s)
    assert any("stt_provider" in w for w in warnings)


def test_invalid_tts_provider():
    s = _settings(
        voice={"tts_provider": "openai"},
    )
    warnings = validate_settings(s)
    assert any("tts_provider" in w for w in warnings)


def test_email_imap_configured_missing_smtp():
    s = _settings(
        email={
            "imap_host": "imap.example.com",
            "smtp_host": "",
            "address": "",
        }
    )
    warnings = validate_settings(s)
    matches = [w for w in warnings if "Email" in w or "email" in w]
    assert len(matches) == 1
    assert "smtp_host" in matches[0]
    assert "address" in matches[0]


def test_approval_disabled_warning():
    s = _settings(approval={"enabled": False})
    warnings = validate_settings(s)
    assert any("approval" in w for w in warnings)


def test_auto_update_low_interval():
    s = _settings(
        auto_update={
            "enabled": True,
            "check_interval_ticks": 5,
        }
    )
    warnings = validate_settings(s)
    assert any(
        "check_interval_ticks" in w for w in warnings
    )
