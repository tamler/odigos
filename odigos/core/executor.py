from odigos.core.context import ContextAssembler
from odigos.providers.base import LLMProvider, LLMResponse


class Executor:
    """Runs the plan -- calls LLM, executes tools.

    Phase 0: Just calls the LLM with assembled context.
    Phase 2+: Will handle tool chains, permission checks, etc.
    """

    def __init__(
        self,
        provider: LLMProvider,
        context_assembler: ContextAssembler,
    ) -> None:
        self.provider = provider
        self.context_assembler = context_assembler

    async def execute(self, conversation_id: str, message_content: str) -> LLMResponse:
        messages = await self.context_assembler.build(conversation_id, message_content)
        return await self.provider.complete(messages)
