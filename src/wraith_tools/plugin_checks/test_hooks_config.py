from pathlib import Path

from wraith_tools.layout import plugin_root

ROOT = Path.cwd()
PLUGIN = plugin_root(ROOT)


def test_plugin_ships_no_hooks():
    # The Claude directory refuses command hooks from unverified orgs.
    for base in {ROOT, PLUGIN}:
        assert not (base / "hooks").exists()
        assert not (base / "com.github.copilot" / "hooks").exists()
