"""Tests for FeedConfig in settings."""
from odigos.config import FeedConfig, Settings


def test_feed_config_defaults():
    cfg = FeedConfig()
    assert cfg.enabled is False
    assert cfg.public is False
    assert cfg.max_entries == 200


def test_settings_includes_feed():
    s = Settings()
    assert hasattr(s, "feed")
    assert s.feed.enabled is False
