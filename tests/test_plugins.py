import json
import sys
import textwrap
from pathlib import Path

import pytest

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
    async def test_load_plugin_registers_hooks(self, db, tmp_path):
        tracer = Tracer(db)
        pm = PluginManager(tracer)

        plugin_file = tmp_path / "my_plugin.py"
        plugin_file.write_text(textwrap.dedent("""\
            async def on_step(event_type, conversation_id, data):
                pass

            hooks = {"step_start": on_step}
        """))

        pm.load_all(str(tmp_path))

        assert len(tracer._subscribers["step_start"]) == 1

    async def test_load_multiple_plugins(self, db, tmp_path):
        tracer = Tracer(db)
        pm = PluginManager(tracer)

        for name in ("alpha", "beta"):
            (tmp_path / f"{name}.py").write_text(textwrap.dedent("""\
                async def on_event(event_type, conversation_id, data):
                    pass

                hooks = {"step_start": on_event}
            """))

        pm.load_all(str(tmp_path))

        assert len(tracer._subscribers["step_start"]) == 2
        assert len(pm.loaded_plugins) == 2

    async def test_skip_file_without_hooks(self, db, tmp_path):
        tracer = Tracer(db)
        pm = PluginManager(tracer)

        (tmp_path / "no_hooks.py").write_text("x = 1\n")
        pm.load_all(str(tmp_path))

        assert len(pm.loaded_plugins) == 0

    async def test_skip_file_with_import_error(self, db, tmp_path):
        tracer = Tracer(db)
        pm = PluginManager(tracer)

        (tmp_path / "bad.py").write_text("import nonexistent_module_xyz\n")
        pm.load_all(str(tmp_path))

        assert len(pm.loaded_plugins) == 0

    async def test_skip_non_dict_hooks(self, db, tmp_path):
        tracer = Tracer(db)
        pm = PluginManager(tracer)

        (tmp_path / "bad_hooks.py").write_text("hooks = [1, 2, 3]\n")
        pm.load_all(str(tmp_path))

        assert len(pm.loaded_plugins) == 0

    async def test_skip_non_callable_hook(self, db, tmp_path):
        tracer = Tracer(db)
        pm = PluginManager(tracer)

        (tmp_path / "non_callable.py").write_text(textwrap.dedent("""\
            hooks = {"step_start": "not_a_function"}
        """))
        pm.load_all(str(tmp_path))

        assert len(pm.loaded_plugins) == 1
        assert pm.loaded_plugins[0]["hook_count"] == 0
        assert len(tracer._subscribers.get("step_start", [])) == 0

    async def test_empty_directory(self, db, tmp_path):
        tracer = Tracer(db)
        pm = PluginManager(tracer)

        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        pm.load_all(str(plugins_dir))

        assert len(pm.loaded_plugins) == 0

    async def test_creates_directory_if_missing(self, db, tmp_path):
        tracer = Tracer(db)
        pm = PluginManager(tracer)

        plugins_dir = tmp_path / "new_plugins_dir"
        assert not plugins_dir.exists()

        pm.load_all(str(plugins_dir))

        assert plugins_dir.exists()
        assert len(pm.loaded_plugins) == 0

    async def test_skips_dunder_files(self, db, tmp_path):
        tracer = Tracer(db)
        pm = PluginManager(tracer)

        (tmp_path / "__init__.py").write_text(textwrap.dedent("""\
            async def on_event(event_type, conversation_id, data):
                pass

            hooks = {"step_start": on_event}
        """))
        pm.load_all(str(tmp_path))

        assert len(pm.loaded_plugins) == 0

    async def test_reload_clears_and_reloads(self, db, tmp_path):
        tracer = Tracer(db)
        pm = PluginManager(tracer)

        plugin_file = tmp_path / "reloadable.py"
        plugin_file.write_text(textwrap.dedent("""\
            async def on_step(event_type, conversation_id, data):
                pass

            hooks = {"step_start": on_step}
        """))

        pm.load_all(str(tmp_path))
        assert len(tracer._subscribers["step_start"]) == 1

        # Rewrite with different hook
        plugin_file.write_text(textwrap.dedent("""\
            async def on_tool(event_type, conversation_id, data):
                pass

            hooks = {"tool_call": on_tool}
        """))

        pm.reload()

        assert len(tracer._subscribers.get("step_start", [])) == 0
        assert len(tracer._subscribers["tool_call"]) == 1
        assert len(pm.loaded_plugins) == 1

    async def test_loaded_plugins_metadata(self, db, tmp_path):
        tracer = Tracer(db)
        pm = PluginManager(tracer)

        plugin_file = tmp_path / "meta_plugin.py"
        plugin_file.write_text(textwrap.dedent("""\
            async def on_a(event_type, conversation_id, data):
                pass

            async def on_b(event_type, conversation_id, data):
                pass

            hooks = {"step_start": on_a, "tool_call": on_b}
        """))

        pm.load_all(str(tmp_path))

        assert len(pm.loaded_plugins) == 1
        meta = pm.loaded_plugins[0]
        assert meta["name"] == "meta_plugin"
        assert meta["file"] == str(plugin_file)
        assert meta["hook_count"] == 2


class TestPluginManagerIntegration:
    async def test_plugin_receives_trace_event(self, db, tmp_path):
        await _seed_conversation(db, "conv-1")
        tracer = Tracer(db)
        pm = PluginManager(tracer)

        plugin_file = tmp_path / "collector.py"
        plugin_file.write_text(textwrap.dedent("""\
            collected = []

            async def on_step(event_type, conversation_id, data):
                collected.append({"event_type": event_type, "conversation_id": conversation_id, "data": data})

            hooks = {"step_start": on_step}
        """))

        pm.load_all(str(tmp_path))

        await tracer.emit("step_start", "conv-1", {"msg": "hello"})

        module = sys.modules["odigos_plugin_collector"]
        assert len(module.collected) == 1
        assert module.collected[0]["event_type"] == "step_start"
        assert module.collected[0]["conversation_id"] == "conv-1"
        assert module.collected[0]["data"] == {"msg": "hello"}
