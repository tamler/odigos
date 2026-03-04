from dataclasses import dataclass


@dataclass
class Plan:
    action: str  # "respond" -- more actions in Phase 2
    requires_tools: bool = False


class Planner:
    """Decides what actions to take for a given message.

    Phase 0: Always returns a simple "respond" plan.
    Phase 1+: Will classify intent, decide on tools, etc.
    """

    async def plan(self, message_content: str) -> Plan:
        return Plan(action="respond", requires_tools=False)
