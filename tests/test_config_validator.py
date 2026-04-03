"""Tests for startup config validation."""

from odigos.config import Settings
from odigos.config_validator import validate_settings


def _settings(**overrides) -> Settings:
    """Build a Settings object with safe defaults."""
    defaults: dict = {
        "llm_api_key": "sk-test-key",
        "services": {"groq": "gsk-test-key"},
    }
    defaults.update(overrides)
    return Settings(**defaults)


def test_valid_config_no_warnings(tmp_path):
    db_path = tmp_path / "odigos.db"
    s = _settings(database={"path": str(db_path)})
    warnings = validate_settings(s)
    assert warnings == []


def test_missing_llm_key():
    s = _settings(llm_api_key="")
    warnings = validate_settings(s)
    assert any("llm_api_key" in w for w in warnings)


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


def test_email_enabled_no_host():
    s = _settings(
        email={
            "enabled": True,
            "address": "",
            "imap_host": "",
            "smtp_host": "",
        }
    )
    warnings = validate_settings(s)
    matches = [w for w in warnings if "Email" in w]
    assert len(matches) == 1
    assert "imap_host" in matches[0]
    assert "smtp_host" in matches[0]
    assert "address" in matches[0]


def test_calendar_enabled_no_url():
    s = _settings(
        calendar={"enabled": True, "url": ""},
    )
    warnings = validate_settings(s)
    assert any("Calendar" in w for w in warnings)


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
