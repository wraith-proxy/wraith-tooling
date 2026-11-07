"""Generate Copilot agent files from agents/*.md."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

KEYS = ("name", "description", "tools")
TARGET = "com.github.copilot/agents"


def render_agent(source_text: str, stem: str) -> str:
    _, head, body = source_text.split("---\n", 2)
    groups: dict[str, list[str]] = {}
    current = None
    for line in head.splitlines(keepends=True):
        if line[:1] not in (" ", "\t", "-", "#") and ":" in line:
            current = line.split(":", 1)[0].strip()
            groups[current] = []
        if current is not None:
            groups[current].append(line)
    front = "".join("".join(groups[k]) for k in KEYS if k in groups)
    note = (
        f"<!-- GENERATED from agents/{stem}.md by "
        "wraith-build-copilot. Do not edit. -->"
    )
    return f"---\n{front}---\n{note}\n\n{body}"


def build(root: Path, check: bool) -> list[str]:
    src_dir = root / "agents"
    out_dir = root / TARGET
    wanted: dict[str, str] = {}
    if src_dir.is_dir():
        for src in sorted(src_dir.glob("*.md")):
            text = src.read_bytes().decode("utf-8")
            wanted[f"{src.stem}.agent.md"] = render_agent(text, src.stem)
    existing = (
        {p.name for p in out_dir.glob("*.agent.md")}
        if out_dir.is_dir()
        else set()
    )
    changed = []
    for name, text in wanted.items():
        path = out_dir / name
        if not path.exists() or (path.read_bytes().decode("utf-8") != text):
            changed.append(f"{TARGET}/{name}")
            if not check:
                out_dir.mkdir(parents=True, exist_ok=True)
                path.write_bytes(text.encode("utf-8"))
    for name in sorted(existing - set(wanted)):
        changed.append(f"{TARGET}/{name}")
        if not check:
            (out_dir / name).unlink()
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args(argv)
    args.root = args.root or Path.cwd()
    changed = build(args.root, args.check)
    if args.check:
        if changed:
            print("\n".join(changed))
            return 1
        print("copilot agents up to date")
        return 0
    print(f"wrote {len(changed)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
