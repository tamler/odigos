from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from odigos.channels.base import UniversalMessage
    from odigos.core.agent import Agent
    from odigos.core.approval import ApprovalGate
    from odigos.core.budget import BudgetTracker
    from odigos.core.goal_store import GoalStore


class AgentService:
    """Facade providing a single entry point for all interaction interfaces.

    Wraps Agent, GoalStore, BudgetTracker, and ApprovalGate so that channels
    and plugins don't need to know about each individual dependency.
    """

    def __init__(
        self,
        agent: Agent,
        goal_store: GoalStore,
        budget_tracker: BudgetTracker,
        approval_gate: ApprovalGate | None = None,
    ) -> None:
        self.agent = agent
        self.goal_store = goal_store
        self.budget_tracker = budget_tracker
        self.approval_gate = approval_gate

    # -- Message handling --

    async def handle_message(self, message: UniversalMessage) -> str:
        """Send a message to the agent and return the response."""
        return await self.agent.handle_message(message)

    # -- Goals / Todos / Reminders --

    async def list_goals(self) -> list[dict]:
        return await self.goal_store.list_goals()

    async def list_todos(self) -> list[dict]:
        return await self.goal_store.list_todos()

    async def list_reminders(self) -> list[dict]:
        return await self.goal_store.list_reminders()

    async def cancel_item(self, item_id: str) -> bool:
        return await self.goal_store.cancel(item_id)

    # -- Budget --

    async def check_budget(self) -> Any:
        return await self.budget_tracker.check_budget()

    # -- Approvals --

    def resolve_approval(self, approval_id: str, decision: str) -> bool:
        if not self.approval_gate:
            return False
        return self.approval_gate.resolve(approval_id, decision)

    # -- Heartbeat --

    def pause_heartbeat(self) -> None:
        if self.agent.heartbeat:
            self.agent.heartbeat.paused = True

    def resume_heartbeat(self) -> None:
        if self.agent.heartbeat:
            self.agent.heartbeat.paused = False

    @property
    def heartbeat_paused(self) -> bool | None:
        if self.agent.heartbeat:
            return self.agent.heartbeat.paused
        return None
