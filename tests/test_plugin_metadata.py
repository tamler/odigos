import pytest
from pathlib import Path

from odigos.core.plugins import PluginManager
from odigos.core.plugin_context import PluginContext
from odigos.tools.registry import ToolRegistry
from odigos.channels.base import ChannelRegistry


@pytest.fixture
def plugin_dir(tmp_path):
    """Create a minimal plugin directory with plugin.yaml."""
    plugin = tmp_path / "testplugin"
    plugin.mkdir()
    (plugin / "__init__.py").write_text(
        'def register(ctx): pass\n'
    )
    (plugin / "plugin.yaml").write_text(
        'name: Test Plugin\n'
        'id: testplugin\n'
        'description: A test plugin\n'
        'category: tools\n'
        'requires: []\n'
        'config_keys:\n'
        '  - key: test_key\n'
        '    required: true\n'
        '    description: A test key\n'
        '    type: string\n'
    )
    return tmp_path


class TestPluginMetadata:
    def test_loaded_plugins_include_status(self, plugin_dir):
        ctx = PluginContext(
            tool_registry=ToolRegistry(),
            channel_registry=ChannelRegistry(),
            config={},
        )
        pm = PluginManager(plugin_context=ctx)
        pm.load_all(str(plugin_dir))
        assert len(pm.loaded_plugins) == 1
        p = pm.loaded_plugins[0]
        assert p["status"] == "active"

    def test_failed_plugin_has_error_status(self, tmp_path):
        plugin = tmp_path / "badplugin"
        plugin.mkdir()
        (plugin / "__init__.py").write_text(
            'def register(ctx): raise ValueError("broken")\n'
        )
        ctx = PluginContext(
            tool_registry=ToolRegistry(),
            channel_registry=ChannelRegistry(),
            config={},
        )
        pm = PluginManager(plugin_context=ctx)
        pm.load_all(str(tmp_path))
        assert len(pm.loaded_plugins) == 1
        p = pm.loaded_plugins[0]
        assert p["status"] == "error"
        assert "broken" in p.get("error_message", "")

    def test_scan_plugin_metadata(self, plugin_dir):
        pm = PluginManager()
        metadata = pm.scan_metadata(str(plugin_dir))
        assert len(metadata) == 1
        m = metadata[0]
        assert m["id"] == "testplugin"
        assert m["name"] == "Test Plugin"
        assert m["category"] == "tools"
        assert len(m["config_keys"]) == 1

    def test_scan_metadata_missing_yaml(self, tmp_path):
        plugin = tmp_path / "noyaml"
        plugin.mkdir()
        (plugin / "__init__.py").write_text('def register(ctx): pass\n')
        pm = PluginManager()
        metadata = pm.scan_metadata(str(tmp_path))
        assert len(metadata) == 1
        assert metadata[0]["id"] == "noyaml"
        assert metadata[0]["name"] == "noyaml"

    def test_scan_metadata_nested_category(self, tmp_path):
        # Create a plugin inside a category subdir (providers/myprovider/)
        cat_dir = tmp_path / "providers"
        cat_dir.mkdir()
        plugin = cat_dir / "myprovider"
        plugin.mkdir()
        (plugin / "__init__.py").write_text('def register(ctx): pass\n')
        (plugin / "plugin.yaml").write_text(
            'name: My Provider\n'
            'id: myprovider\n'
            'description: A provider plugin\n'
            'category: providers\n'
            'requires: []\n'
            'config_keys: []\n'
        )
        pm = PluginManager()
        metadata = pm.scan_metadata(str(tmp_path))
        assert len(metadata) == 1
        assert metadata[0]["id"] == "myprovider"
        assert metadata[0]["category"] == "providers"
