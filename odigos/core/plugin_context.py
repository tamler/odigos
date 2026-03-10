from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from odigos.channels.base import Channel, ChannelRegistry
    from odigos.core.trace import Tracer
    from odigos.tools.base import BaseTool
    from odigos.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class PluginContext:
    """Context object passed to plugin register() functions.

    Provides extension points for tools, channels, and providers.
    """

    def __init__(
        self,
        tool_registry: ToolRegistry | None = None,
        channel_registry: ChannelRegistry | None = None,
        tracer: Tracer | None = None,
        config: dict | None = None,
    ) -> None:
        self.tool_registry = tool_registry
        self.channel_registry = channel_registry
        self.tracer = tracer
        self.config = config or {}
        self._providers: dict[str, Any] = {}

    def register_tool(self, tool: BaseTool) -> None:
        """Register a tool into the agent's tool registry."""
        if self.tool_registry is None:
            logger.warning("Cannot register tool '%s': no tool registry", tool.name)
            return
        self.tool_registry.register(tool)
        logger.info("Plugin registered tool: %s", tool.name)

    def register_channel(self, name: str, channel: Channel) -> None:
        """Register a communication channel."""
        if self.channel_registry is None:
            logger.warning("Cannot register channel '%s': no channel registry", name)
            return
        self.channel_registry.register(name, channel)
        logger.info("Plugin registered channel: %s", name)

    def register_provider(self, name: str, provider: Any) -> None:
        """Register a provider (LLM, embedding, vector, document, etc.)."""
        self._providers[name] = provider
        logger.info("Plugin registered provider: %s", name)

    def get_provider(self, name: str) -> Any | None:
        """Retrieve a registered provider by name."""
        return self._providers.get(name)
