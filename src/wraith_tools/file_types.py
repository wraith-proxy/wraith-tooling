"""Enforce the Claude plugin directory file policy on tracked files."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

TEXT_EXTS = {".md", ".txt", ".json", ".yaml", ".yml"}
IMAGE_MAGIC = {
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".gif": (b"GIF87a", b"GIF89a"),
    ".webp": (b"RIFF",),
    ".ico": (b"\x00\x00\x01\x00",),
}
ALLOWED_NAMES = {"LICENSE", ".gitignore"}
PACKAGE_FILES = {
    "package.json",
    "pnpm-workspace.yaml",
    "pyproject.toml",
    "uv.lock",
    "Pipfile",
    "poetry.lock",
    "package-lock.json",
    "yarn.lock",
}


def _is_package_file(name: str) -> bool:
    if name in PACKAGE_FILES:
        return True
    return name.startswith("requirements") and name.endswith(".txt")


def check_file(path: Path, rel: str) -> str | None:
    name = path.name
    ext = path.suffix.lower()
    if _is_package_file(name):
        return "package manager config"
    if name not in ALLOWED_NAMES and ext not in TEXT_EXTS | set(IMAGE_MAGIC):
        return "file type not allowed"
    data = path.read_bytes()
    if data[:2] == b"#!":
        return "starts with a shebang"
    if ext in IMAGE_MAGIC:
        if not data.startswith(IMAGE_MAGIC[ext]):
            return "image magic bytes do not match extension"
        if ext == ".webp" and data[8:12] != b"WEBP":
            return "image magic bytes do not match extension"
        return None
    if b"\x00" in data:
        return "contains a NUL byte"
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return "not valid UTF-8"
    return None


def tracked_files(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        capture_output=True,
        check=True,
    ).stdout
    return [f for f in out.decode("utf-8").split("\0") if f]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    root = Path.cwd()
    failed = 0
    for rel in tracked_files(root):
        path = root / rel
        if not path.is_file():
            continue
        reason = check_file(path, rel)
        if reason:
            print(f"{rel}: {reason}")
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
