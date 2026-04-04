"""Heartbeat background loop — decomposed into focused modules."""
# During migration: re-export from old monolith
from odigos.core.heartbeat_old import Heartbeat

__all__ = ["Heartbeat"]
