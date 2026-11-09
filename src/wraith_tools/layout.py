"""Find the plugin folder from the marketplace manifest.

A repo without .claude-plugin/marketplace.json, or whose single plugin
source is "./", is its own plugin root, so older layouts keep working.
"""

from __future__ import annotations

import json
from pathlib import Path


def plugin_root(repo: Path) -> Path:
    repo = Path(repo)
    path = repo / ".claude-plugin" / "marketplace.json"
    if not path.is_file():
        return repo
    plugins = json.loads(path.read_text(encoding="utf-8"))["plugins"]
    source = plugins[0]["source"]
    if (
        not isinstance(source, str)
        or not source.startswith("./")
        or ".." in Path(source).parts
    ):
        raise ValueError(f"unsupported plugin source: {source!r}")
    rel = source[2:].strip("/")
    return repo / rel if rel else repo
