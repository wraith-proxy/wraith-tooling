"""Pick the commit type for an upstream sync from its changed paths.

When the marketplace source is the repository root, everything ships
unless it is listed here. When the plugin lives in a subfolder, only paths
under that folder ship. A sync that changes only non-shipped paths is a
chore and does not cut a release.
"""

from __future__ import annotations

import sys
from pathlib import Path

from wraith_tools.layout import plugin_root

NON_SHIPPED_DIRS = {"scripts", "tests", "evals", "docs", ".github"}
NON_SHIPPED_FILES = {"pyproject.toml", "uv.lock", "upstream-pins.txt"}


def is_shipped(path: str, prefix: str = "") -> bool:
    if prefix:
        return path.startswith(prefix)
    head, sep, _ = path.partition("/")
    if sep:
        return head not in NON_SHIPPED_DIRS
    return path not in NON_SHIPPED_FILES and not path.startswith(".")


def commit_type(paths: list[str], prefix: str = "") -> str:
    shipped = any(is_shipped(p, prefix) for p in paths)
    return "fix" if shipped else "chore"


def main() -> None:
    repo = Path.cwd()
    root = plugin_root(repo)
    prefix = "" if root == repo else root.relative_to(repo).as_posix() + "/"
    paths = [line.strip() for line in sys.stdin if line.strip()]
    print(commit_type(paths, prefix))


if __name__ == "__main__":
    main()
