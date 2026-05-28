"""find_tools coverage gate (brittleness audit Phase B.3).

Every registered tool must be reachable through find_tools for at least one
natural-language query. If a tool is undiscoverable, the agent can never use
it no matter how capable the model is — the find_tools loop bug (2026-05-28)
was partly caused by sparse, hard-to-match tool surfacing.

PR REQUIREMENT: when you add a tool, add >=3 seed queries below that should
surface it. CI fails on any uncovered tool and prints which ones, so this is
never a surprise — the fix is "add seed queries for your tool."

See docs/superpowers/specs/2026-05-28-brittleness-audit-and-robustness.md §B.3.

This test does a real (network-light) tool registration. It is marked slow
because it boots the tool layer; run with `-m slow` or it runs in full CI.
"""
from __future__ import annotations

import pytest
import pytest_asyncio

# Curated natural-language queries an agent might search for when it needs a
# tool. Grouped by capability. Add >=3 per new tool.
QUERIES = [
    # productivity / tasks
    "create a kanban board", "add a card to my board", "make a task list",
    "set a reminder", "create a todo", "track a goal", "move a card",
    "update a card", "delete a card", "list my boards", "show board details",
    # communication
    "send an email", "check my inbox", "search email", "read an email",
    "schedule a meeting", "find a free time slot", "create calendar event",
    "check my calendar",
    # knowledge / memory
    "remember a fact", "look up something I told you", "search my notes",
    "create a notebook", "add a note", "summarize a document",
    "search the web", "read a webpage", "search my workspace",
    # creative
    "generate an image", "create a picture", "make a song", "generate music",
    "process audio", "transcribe audio", "make a slide deck",
    "translate text", "make a podcast", "generate a quiz", "create a mindmap",
    "generate a qr code", "create a card", "import a card",
    # files / docs / data
    "manage files", "read a file", "save a file", "process a document",
    "process an image", "create a spreadsheet", "make a data table",
    "create an artifact", "delete an artifact",
    # workflow / planning
    "decompose a query", "check a plan", "update a plan",
    "run a subagent", "dispatch parallel work", "check subagent status",
    "cancel a subagent",
    # skills / discovery / system
    "find tools", "activate a skill", "create a new skill", "update a skill",
    "configure settings", "send a notification", "speak text aloud",
    "suggest actions", "grade a response",
    # code
    "run python code", "execute code",
    # feeds / publishing / agents
    "publish to feed", "watch a feed", "list feeds", "read a feed",
    "check feeds", "message another agent",
    # templates / quiz
    "browse agent templates", "adopt an agent template", "grade a quiz",
    "create a quiz from text",
]


@pytest_asyncio.fixture
async def booted_registry():
    """Boot just enough of the agent to populate the tool registry.

    Discovers required init steps empirically — if more are needed the test
    fails loudly with the missing attribute, which is the signal to add it.
    """
    import os
    import tempfile

    from odigos.bootstrap import Bootstrapper
    from tests.conftest import make_test_settings

    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    settings = make_test_settings(database={"path": db_path})
    boot = Bootstrapper(settings=settings)
    await boot.init_database()
    await boot.init_llm()
    await boot.init_embeddings()
    await boot.init_memory()
    await boot.init_tools()
    try:
        await boot.init_plugins()
    except Exception:
        # plugins are best-effort (network / optional deps); core tools are
        # what we gate on.
        pass

    yield boot.container

    conn = getattr(boot.container.db, "_conn", None)
    if conn is not None:
        await conn.close()
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.mark.slow
@pytest.mark.asyncio
async def test_every_tool_is_discoverable(booted_registry):
    container = booted_registry
    registry = container.tool_registry
    from odigos.tools.find_tools import FindToolsTool

    all_tools = {t.name for t in registry.list()}
    assert all_tools, "no tools registered — bootstrap problem"

    finder = FindToolsTool(
        registry=registry,
        skill_registry=getattr(container, "skill_registry", None),
    )

    covered: set[str] = set()
    for q in QUERIES:
        res = await finder.execute({"query": q})
        if not res.success:
            continue
        for name in all_tools:
            if name in res.data:
                covered.add(name)

    uncovered = sorted(all_tools - covered)
    assert not uncovered, (
        f"{len(uncovered)} tool(s) not discoverable via find_tools: {uncovered}. "
        "Add >=3 seed queries for each to QUERIES in this file."
    )
