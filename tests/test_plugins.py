import importlib.util
import json
import logging
import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from odigos.core.plugin_context import PluginContext
from odigos.core.plugins import PluginManager
from odigos.core.trace import Tracer
from odigos.db import Database


@pytest.fixture
async def db(tmp_db_path: str):
    database = Database(tmp_db_path, migrations_dir="migrations")
    await database.initialize()
    yield database
    await database.close()


async def _seed_conversation(db: Database, conversation_id: str) -> None:
    await db.execute(
        "INSERT INTO conversations (id, channel) VALUES (?, ?)",
        (conversation_id, "test"),
    )


class TestPluginManager:
    async def test_load_plugin_registers_via_register(self, db, tmp_path):
        tracer = Tracer(db)
        ctx = PluginContext(tracer=tracer)
        pm = PluginManager(plugin_context=ctx)

        plugin_file = tmp_path / "my_plugin.py"
        plugin_file.write_text(textwrap.dedent("""\
            async def on_step(event_type, conversation_id, data):
                pass

            def register(ctx):
                ctx.tracer.subscribe("step_start", on_step)
        """))

        pm.load_all(str(tmp_path))

        assert len(tracer._subscribers["step_start"]) == 1

    async def test_load_multiple_plugins(self, db, tmp_path):
        tracer = Tracer(db)
        ctx = PluginContext(tracer=tracer)
        pm = PluginManager(plugin_context=ctx)

        for name in ("alpha", "beta"):
            (tmp_path / f"{name}.py").write_text(textwrap.dedent("""\
                async def on_event(event_type, conversation_id, data):
                    pass

                def register(ctx):
                    ctx.tracer.subscribe("step_start", on_event)
            """))

        pm.load_all(str(tmp_path))

        assert len(tracer._subscribers["step_start"]) == 2
        assert len(pm.loaded_plugins) == 2

    async def test_skip_file_without_register(self, db, tmp_path):
        tracer = Tracer(db)
        ctx = PluginContext(tracer=tracer)
        pm = PluginManager(plugin_context=ctx)

        (tmp_path / "no_register.py").write_text("x = 1\n")
        pm.load_all(str(tmp_path))

        assert len(pm.loaded_plugins) == 1
        assert pm.loaded_plugins[0]["status"] == "error"
        assert pm.loaded_plugins[0]["pattern"] == "none"

    async def test_skip_file_with_import_error(self, db, tmp_path):
        tracer = Tracer(db)
        pm = PluginManager(tracer=tracer)

        (tmp_path / "bad.py").write_text("import nonexistent_module_xyz\n")
        pm.load_all(str(tmp_path))

        assert len(pm.loaded_plugins) == 1
        assert pm.loaded_plugins[0]["status"] == "error"
        assert pm.loaded_plugins[0]["pattern"] == "import"

    async def test_skip_non_callable_register(self, db, tmp_path):
        tracer = Tracer(db)
        ctx = PluginContext(tracer=tracer)
        pm = PluginManager(plugin_context=ctx)

        (tmp_path / "bad_register.py").write_text("register = 'not_a_function'\n")
        pm.load_all(str(tmp_path))

        assert len(pm.loaded_plugins) == 1
        assert pm.loaded_plugins[0]["status"] == "error"

    async def test_empty_directory(self, db, tmp_path):
        tracer = Tracer(db)
        ctx = PluginContext(tracer=tracer)
        pm = PluginManager(plugin_context=ctx)

        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        pm.load_all(str(plugins_dir))

        assert len(pm.loaded_plugins) == 0

    async def test_creates_directory_if_missing(self, db, tmp_path):
        tracer = Tracer(db)
        ctx = PluginContext(tracer=tracer)
        pm = PluginManager(plugin_context=ctx)

        plugins_dir = tmp_path / "new_plugins_dir"
        assert not plugins_dir.exists()

        pm.load_all(str(plugins_dir))

        assert plugins_dir.exists()
        assert len(pm.loaded_plugins) == 0

    async def test_skips_dunder_files(self, db, tmp_path):
        tracer = Tracer(db)
        ctx = PluginContext(tracer=tracer)
        pm = PluginManager(plugin_context=ctx)

        (tmp_path / "__init__.py").write_text(textwrap.dedent("""\
            def register(ctx):
                ctx.tracer.subscribe("step_start", lambda *a: None)
        """))
        pm.load_all(str(tmp_path))

        assert len(pm.loaded_plugins) == 0

    async def test_reload_clears_and_reloads(self, db, tmp_path):
        tracer = Tracer(db)
        ctx = PluginContext(tracer=tracer)
        pm = PluginManager(plugin_context=ctx)

        plugin_file = tmp_path / "reloadable.py"
        plugin_file.write_text(textwrap.dedent("""\
            async def on_step(event_type, conversation_id, data):
                pass

            def register(ctx):
                ctx.tracer.subscribe("step_start", on_step)
        """))

        pm.load_all(str(tmp_path))
        assert len(tracer._subscribers["step_start"]) == 1

        # Rewrite with different subscription
        plugin_file.write_text(textwrap.dedent("""\
            async def on_tool(event_type, conversation_id, data):
                pass

            def register(ctx):
                ctx.tracer.subscribe("tool_call", on_tool)
        """))

        pm.reload()

        assert len(tracer._subscribers.get("step_start", [])) == 0
        assert len(tracer._subscribers["tool_call"]) == 1
        assert len(pm.loaded_plugins) == 1

    async def test_loaded_plugins_metadata(self, db, tmp_path):
        tracer = Tracer(db)
        ctx = PluginContext(tracer=tracer)
        pm = PluginManager(plugin_context=ctx)

        plugin_file = tmp_path / "meta_plugin.py"
        plugin_file.write_text(textwrap.dedent("""\
            def register(ctx):
                pass
        """))

        pm.load_all(str(tmp_path))

        assert len(pm.loaded_plugins) == 1
        meta = pm.loaded_plugins[0]
        assert meta["name"] == "meta_plugin"
        assert meta["file"] == str(plugin_file)
        assert meta["pattern"] == "register"
        assert meta["status"] == "active"


class TestPluginManagerIntegration:
    async def test_plugin_receives_trace_event(self, db, tmp_path):
        await _seed_conversation(db, "conv-1")
        tracer = Tracer(db)
        ctx = PluginContext(tracer=tracer)
        pm = PluginManager(plugin_context=ctx)

        plugin_file = tmp_path / "collector.py"
        plugin_file.write_text(textwrap.dedent("""\
            collected = []

            async def on_step(event_type, conversation_id, data):
                collected.append({"event_type": event_type, "conversation_id": conversation_id, "data": data})

            def register(ctx):
                ctx.tracer.subscribe("step_start", on_step)
        """))

        pm.load_all(str(tmp_path))

        await tracer.emit("step_start", "conv-1", {"msg": "hello"})

        module = sys.modules["odigos_plugin_collector"]
        assert len(module.collected) == 1
        assert module.collected[0]["event_type"] == "step_start"
        assert module.collected[0]["conversation_id"] == "conv-1"
        assert module.collected[0]["data"] == {"msg": "hello"}


_SAMPLE_PLUGIN_PATH = str(
    Path(__file__).resolve().parent.parent / "data" / "plugins" / "log_tools.py"
)


class TestSamplePlugin:
    def test_register_function_exists(self):
        spec = importlib.util.spec_from_file_location(
            "log_tools_test", _SAMPLE_PLUGIN_PATH
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        assert hasattr(module, "register")
        assert callable(module.register)

    async def test_register_subscribes_tracer(self, db):
        tracer = Tracer(db)
        ctx = PluginContext(tracer=tracer)

        spec = importlib.util.spec_from_file_location(
            "log_tools_test2", _SAMPLE_PLUGIN_PATH
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        module.register(ctx)

        assert len(tracer._subscribers.get("tool_call", [])) == 1
        assert len(tracer._subscribers.get("tool_result", [])) == 1


class TestPluginContext:
    def test_register_tool(self):
        """PluginContext.register_tool() adds tool to the registry."""
        from odigos.core.plugin_context import PluginContext
        from odigos.tools.registry import ToolRegistry
        from odigos.tools.base import BaseTool, ToolResult

        class DummyTool(BaseTool):
            name = "dummy"
            description = "test"
            parameters_schema = {}
            async def execute(self, params): return ToolResult(success=True, data="ok")

        tool_registry = ToolRegistry()
        ctx = PluginContext(tool_registry=tool_registry)
        ctx.register_tool(DummyTool())

        assert tool_registry.get("dummy") is not None

    def test_register_provider(self):
        """PluginContext.register_provider() stores provider by name."""
        from odigos.core.plugin_context import PluginContext

        ctx = PluginContext()
        ctx.register_provider("my_llm", object())
        assert ctx.get_provider("my_llm") is not None

    def test_register_channel(self):
        """PluginContext.register_channel() adds to channel registry."""
        from odigos.channels.base import ChannelRegistry
        from odigos.core.plugin_context import PluginContext

        channel_registry = ChannelRegistry()
        ctx = PluginContext(channel_registry=channel_registry)

        mock_channel = MagicMock()
        ctx.register_channel("discord", mock_channel)
        assert channel_registry.for_conversation("discord:123") is not None

    def test_register_tool_no_registry_warns(self, caplog):
        """PluginContext.register_tool() warns when no registry is set."""
        from odigos.core.plugin_context import PluginContext
        from odigos.tools.base import BaseTool, ToolResult

        class DummyTool(BaseTool):
            name = "dummy"
            description = "test"
            parameters_schema = {}
            async def execute(self, params): return ToolResult(success=True, data="ok")

        ctx = PluginContext()
        with caplog.at_level(logging.WARNING):
            ctx.register_tool(DummyTool())
        assert "no tool registry" in caplog.text

    def test_register_channel_no_registry_warns(self, caplog):
        """PluginContext.register_channel() warns when no registry is set."""
        from odigos.core.plugin_context import PluginContext

        ctx = PluginContext()
        with caplog.at_level(logging.WARNING):
            ctx.register_channel("discord", MagicMock())
        assert "no channel registry" in caplog.text

    def test_get_provider_returns_none_for_missing(self):
        """PluginContext.get_provider() returns None for unregistered name."""
        from odigos.core.plugin_context import PluginContext

        ctx = PluginContext()
        assert ctx.get_provider("nonexistent") is None


class TestPluginLoader:
    def test_loads_register_function_plugins(self, tmp_path):
        """PluginManager loads plugins with register(ctx) pattern."""
        from odigos.core.plugin_context import PluginContext
        from odigos.tools.registry import ToolRegistry

        # Create a test plugin
        plugin_file = tmp_path / "test_plugin.py"
        plugin_file.write_text(textwrap.dedent("""\
            from odigos.tools.base import BaseTool, ToolResult

            class TestTool(BaseTool):
                name = "test_plugin_tool"
                description = "from plugin"
                parameters_schema = {}
                async def execute(self, params): return ToolResult(success=True, data="ok")

            def register(ctx):
                ctx.register_tool(TestTool())
        """))

        tool_registry = ToolRegistry()
        ctx = PluginContext(tool_registry=tool_registry)
        manager = PluginManager(plugin_context=ctx)
        manager.load_all(str(tmp_path))

        assert tool_registry.get("test_plugin_tool") is not None
        assert len(manager.loaded_plugins) == 1
        assert manager.loaded_plugins[0]["pattern"] == "register"

    def test_loads_subdirectory_plugins(self, tmp_path):
        """PluginManager loads plugins from providers/tools/channels subdirs."""
        from odigos.core.plugin_context import PluginContext

        providers_dir = tmp_path / "providers" / "my_provider"
        providers_dir.mkdir(parents=True)
        (providers_dir / "__init__.py").write_text(textwrap.dedent("""\
            def register(ctx):
                ctx.register_provider("my_provider", {"loaded": True})
        """))

        ctx = PluginContext()
        manager = PluginManager(plugin_context=ctx)
        manager.load_all(str(tmp_path))

        assert ctx.get_provider("my_provider") is not None
        assert len(manager.loaded_plugins) == 1

    def test_loads_package_plugins(self, tmp_path):
        """PluginManager loads plugins from directories with __init__.py."""
        from odigos.core.plugin_context import PluginContext

        pkg_dir = tmp_path / "my_package"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text(textwrap.dedent("""\
            def register(ctx):
                ctx.register_provider("pkg_provider", {"loaded": True})
        """))

        ctx = PluginContext()
        manager = PluginManager(plugin_context=ctx)
        manager.load_all(str(tmp_path))

        assert ctx.get_provider("pkg_provider") is not None

    def test_rejects_plugin_without_register(self, tmp_path, db):
        """Plugins without register() are rejected."""
        from odigos.core.plugin_context import PluginContext

        plugin_file = tmp_path / "no_register_plugin.py"
        plugin_file.write_text(textwrap.dedent("""\
            async def on_tool_call(event_type, conversation_id, data):
                pass
        """))

        tracer = Tracer(db=db)
        ctx = PluginContext(tracer=tracer)
        manager = PluginManager(plugin_context=ctx)
        manager.load_all(str(tmp_path))

        assert len(manager.loaded_plugins) == 1
        assert manager.loaded_plugins[0]["status"] == "error"
        assert manager.loaded_plugins[0]["pattern"] == "none"
