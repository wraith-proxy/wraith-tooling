import json
from pathlib import Path

import yaml

from wraith_tools.layout import plugin_root

ROOT = Path.cwd()
PLUGIN = plugin_root(ROOT)
ALLOWED = {
    ".claude-plugin",
    "plugin.json",
    "com.github.copilot",
    "skills",
    "agents",
    "assets",
    "README.md",
    "LICENSE",
    "PRIVACY.md",
    "TERMS.md",
    "SUPPORT.md",
    "THIRD_PARTY_NOTICES.md",
}

URL = "https://github.com/wraith-proxy/wraith-skills"
SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
CLAUDE_KEYS = {
    "name",
    "displayName",
    "version",
    "description",
    "author",
    "homepage",
    "repository",
    "license",
    "keywords",
    "icon",
    "documentationUrl",
    "supportUrl",
    "privacyPolicyUrl",
    "termsOfServiceUrl",
}


def load(*parts):
    return json.loads(ROOT.joinpath(*parts).read_text(encoding="utf-8"))


def test_claude_manifest_fields():
    data = json.loads(
        (PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    assert data["name"] == "wraith"
    assert data["license"] == "MIT"
    assert data["repository"] == URL
    assert data["homepage"] == URL
    assert set(data) <= CLAUDE_KEYS


def test_copilot_manifest_fields():
    data = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    assert data["$schema"] == SCHEMA
    assert data["name"] == "wraith"
    assert data["license"] == "MIT"
    for key in ("skills", "agents", "hooks", "mcpServers", "commands"):
        assert key not in data


def test_marketplace_entry():
    data = load(".claude-plugin", "marketplace.json")
    assert data["name"] == "wraith-proxy"
    assert len(data["plugins"]) == 1
    assert data["plugins"][0]["name"] == "wraith"
    assert (ROOT / data["plugins"][0]["source"]).resolve() == PLUGIN.resolve()


def test_manifest_versions_match():
    text = (ROOT / ".cz.yaml").read_text(encoding="utf-8")
    py = str(yaml.safe_load(text)["commitizen"]["version"])
    claude = json.loads(
        (PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )["version"]
    copilot = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))[
        "version"
    ]
    assert py == claude == copilot


def test_plugin_folder_holds_only_plugin_content():
    if PLUGIN == ROOT:
        return
    assert {p.name for p in PLUGIN.iterdir()} <= ALLOWED
    assert (PLUGIN / "LICENSE").read_bytes() == (ROOT / "LICENSE").read_bytes()
    readme = (PLUGIN / "README.md").read_text(encoding="utf-8")
    assert len(readme.split()) >= 40
