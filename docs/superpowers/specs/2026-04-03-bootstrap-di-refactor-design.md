# Bootstrap & Dependency Injection Refactor

**Date:** 2026-04-03
**Status:** Approved
**Goal:** Decompose the monolithic lifespan into testable phases, replace global state with proper dependency injection, and group routers into logical modules.

## Problem

1. `odigos/main.py` lifespan is ~400 lines handling database, LLM, embeddings, memory, tools, plugins, and background loops. A failure in any component prevents the entire agent from starting. Impossible to unit test.

2. Module-level globals (`_db`, `_provider`) and `app.state.*` tightly couple components. Can't run multiple instances or test in isolation.

3. 40+ routers included in a flat list. Hard to navigate.

## Design

### 1. Bootstrapper (odigos/bootstrap.py)

New file. A class that initializes components in isolated phases. Each phase returns its product and can be tested independently.

```python
class Bootstrapper:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.container = Container()

    async def init_database(self) -> Database:
        """Phase 1: Database connection and migrations."""

    async def init_llm(self) -> LLMProvider:
        """Phase 2: LLM provider setup."""

    async def init_embeddings(self) -> EmbeddingsProvider:
        """Phase 3: Embeddings (local or remote)."""

    async def init_memory(self, db: Database, embeddings: EmbeddingsProvider) -> MemoryManager:
        """Phase 4: Memory subsystem (vectors, graph, summarizer)."""

    async def init_tools(self, db: Database) -> ToolRegistry:
        """Phase 5: Register all tools based on settings/services."""

    async def init_plugins(self, db: Database, registry: ToolRegistry) -> list:
        """Phase 6: Load plugins. Non-critical — catches exceptions, logs warnings."""

    async def init_background(self, db: Database, agent: Agent) -> None:
        """Phase 7: Heartbeat, cron, background loops. Non-critical."""

    async def bootstrap(self) -> Container:
        """Run all phases in order. Returns populated Container."""
```

**Critical vs non-critical phases:**
- Phases 1-4 (db, llm, embeddings, memory): fail fast with clear error
- Phases 5-7 (tools, plugins, background): catch exceptions, log warnings, continue

**The lifespan function becomes:**
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    bootstrapper = Bootstrapper(settings)
    container = await bootstrapper.bootstrap()
    app.state.container = container
    yield
    await container.shutdown()
```

### 2. Container (odigos/container.py)

New file. Holds all initialized services. Injected via FastAPI Depends.

```python
@dataclass
class Container:
    settings: Settings | None = None
    db: Database | None = None
    llm_provider: LLMProvider | None = None
    embeddings: EmbeddingsProvider | None = None
    memory: MemoryManager | None = None
    tool_registry: ToolRegistry | None = None
    agent: Agent | None = None
    skill_registry: SkillRegistry | None = None

    async def shutdown(self) -> None:
        """Clean shutdown of all components."""
        if self.db:
            await self.db.close()
```

**Dependency bridge (odigos/api/deps.py changes):**

The existing `get_db`, `get_agent`, `get_settings` functions change from:
```python
def get_db(request: Request):
    return request.app.state.db
```
To:
```python
def get_container(request: Request) -> Container:
    return request.app.state.container

def get_db(container: Container = Depends(get_container)) -> Database:
    return container.db
```

Route handlers don't change — they already use `Depends(get_db)`, `Depends(get_agent)`, etc.

### 3. Router Grouping

Group routers into logical sub-modules:

```
odigos/api/
  workspace/             → notebooks, kanban, artifacts, documents, sharing
    notebooks.py, kanban.py, artifacts.py, documents.py, sharing.py
  agent/                 → conversations, messages, ws, agent_ws, state, agent_message, goals, memory
    conversations.py, message.py, ws.py, agent_ws.py, state.py,
    agent_message.py, goals.py, memory.py, agents.py
  system/                → settings, auth, setup, diagnostic, metrics, cron, budget, push, webauthn, platform_auth
    settings.py, auth.py, setup.py, diagnostic.py, metrics.py,
    cron.py, budget.py, push.py, webauthn.py, platform_auth.py
  content/               → skills, plugins, evolution, prompts, analytics, report
    skills.py, plugins.py, evolution.py, prompts.py, analytics.py, report.py
  media/                 → upload, audio, feed, cards, mesh
    upload.py, audio.py, feed.py, cards.py, mesh.py
```

All 35 routers accounted for. Each `__init__.py` exports a combined router.

Each `__init__.py` exports a single router:
```python
# odigos/api/workspace/__init__.py
from fastapi import APIRouter
from .notebooks import router as notebooks_router
from .kanban import router as kanban_router
from .artifacts import router as artifacts_router

router = APIRouter()
router.include_router(notebooks_router)
router.include_router(kanban_router)
router.include_router(artifacts_router)
```

**main.py includes ~5 routers instead of 40+:**
```python
from odigos.api.workspace import router as workspace_router
from odigos.api.agent import router as agent_router
from odigos.api.system import router as system_router
from odigos.api.tools import router as tools_router
from odigos.api.media import router as media_router
```

### 4. Tool Registration Consolidation

The current tool registration in lifespan has ~200 lines of conditional tool setup. Move this into the Bootstrapper's `init_tools` method, organized by category:

```python
async def init_tools(self, db: Database) -> ToolRegistry:
    registry = ToolRegistry()
    self._register_core_tools(registry, db)      # search, memory, files, code
    self._register_workspace_tools(registry, db)  # notebooks, kanban, workspace search
    self._register_media_tools(registry, db)      # image gen, music gen, audio, QR
    self._register_comms_tools(registry, db)       # email, calendar, notify
    self._register_productivity_tools(registry, db) # goals, todos, plans, data tables
    return registry
```

Each `_register_*` method checks `self.settings.service_key()` / config to decide what to register. All in one place, organized by domain.

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `odigos/bootstrap.py` | Create | Bootstrapper class with phased initialization |
| `odigos/container.py` | Create | Container dataclass holding all services |
| `odigos/main.py` | Rewrite | Slim lifespan (~30 lines), grouped router includes |
| `odigos/api/deps.py` | Modify | Bridge deps to read from Container |
| `odigos/api/workspace/__init__.py` | Create | Combined workspace router |
| `odigos/api/agent/__init__.py` | Create | Combined agent router |
| `odigos/api/system/__init__.py` | Create | Combined system router |
| `odigos/api/tools/__init__.py` | Create | Combined tools router |
| `odigos/api/media/__init__.py` | Create | Combined media router |
| `odigos/api/*.py` | Move | Individual routers move into group dirs |

## Migration Strategy

No legacy concerns (per user direction). Clean break:
1. Create Container and Bootstrapper
2. Move tool registration into Bootstrapper
3. Update deps.py to use Container
4. Move router files into group directories
5. Slim down main.py
6. Delete module-level globals

## What This Does NOT Change

- Route URLs (all prefixes stay the same)
- Route handler signatures (they already use Depends)
- Test fixtures (they inject DB directly)
- config.yaml format
- Frontend API calls
