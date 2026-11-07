from pathlib import Path

ROOT = Path.cwd()


def test_plugin_ships_no_hooks():
    # The Claude directory refuses command hooks from unverified orgs.
    assert not (ROOT / "hooks").exists()
    assert not (ROOT / "com.github.copilot" / "hooks").exists()
