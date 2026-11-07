"""Pick the commit type for an upstream sync from its changed paths.

The marketplace source is the repository root, so everything ships unless
it is listed here. A sync that changes only non-shipped paths is a chore
and does not cut a release.
"""

from __future__ import annotations

import sys

NON_SHIPPED_DIRS = {"scripts", "tests", "evals", "docs", ".github"}
NON_SHIPPED_FILES = {"pyproject.toml", "uv.lock", "upstream-pins.txt"}


def is_shipped(path: str) -> bool:
    head, sep, _ = path.partition("/")
    if sep:
        return head not in NON_SHIPPED_DIRS
    return path not in NON_SHIPPED_FILES and not path.startswith(".")


def commit_type(paths: list[str]) -> str:
    return "fix" if any(is_shipped(p) for p in paths) else "chore"


def main() -> None:
    paths = [line.strip() for line in sys.stdin if line.strip()]
    print(commit_type(paths))


if __name__ == "__main__":
    main()
