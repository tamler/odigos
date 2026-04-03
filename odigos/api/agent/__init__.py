from fastapi import APIRouter

from odigos.api.conversations import router as conversations_router
from odigos.api.message import router as message_router
from odigos.api.ws import router as ws_router
from odigos.api.agent_ws import router as agent_ws_router
from odigos.api.state import router as state_router
from odigos.api.agent_message import router as agent_message_router
from odigos.api.goals import router as goals_router
from odigos.api.memory import router as memory_router
from odigos.api.agents import router as agents_router

router = APIRouter()
router.include_router(conversations_router)
router.include_router(message_router)
router.include_router(ws_router)
router.include_router(agent_ws_router)
router.include_router(state_router)
router.include_router(agent_message_router)
router.include_router(goals_router)
router.include_router(memory_router)
router.include_router(agents_router)
