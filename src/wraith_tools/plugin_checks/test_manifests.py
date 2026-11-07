import json
from pathlib import Path

import yaml

ROOT = Path.cwd()
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
    data = load(".claude-plugin", "plugin.json")
    assert data["name"] == "wraith"
    assert data["license"] == "MIT"
    assert data["repository"] == URL
    assert data["homepage"] == URL
    assert set(data) <= CLAUDE_KEYS


def test_copilot_manifest_fields():
    data = load("plugin.json")
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
    assert data["plugins"][0]["source"] == "./"


def test_manifest_versions_match():
    text = (ROOT / ".cz.yaml").read_text(encoding="utf-8")
    py = str(yaml.safe_load(text)["commitizen"]["version"])
    claude = load(".claude-plugin", "plugin.json")["version"]
    copilot = load("plugin.json")["version"]
    assert py == claude == copilot
