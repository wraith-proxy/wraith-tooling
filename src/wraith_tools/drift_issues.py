"""Decide what to do with each companion's re-vet issue (#91).

Reads the drift section of sync-report.md and the repository's issues
(`gh issue list --state all --json number,title,state,body`). For each
companion with drift it writes body-<KEY>.md and prints one action:

- `keep KEY N`: an open `re-vet KEY` issue already shows this drift
  fingerprint; leave it alone, and do not re-vet it again (#95).
- `edit KEY N`: an open `re-vet KEY` issue shows older drift; refresh it.
- `skip KEY N`: a closed `re-vet KEY` issue already carries this drift
  fingerprint, so the owner has seen these exact changes; leave it closed.
- `create KEY`: open a new `re-vet KEY` issue.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

HEADING = "## Companion drift"
MARKER = re.compile(r"drift-fingerprint: (\w+ [0-9a-f]{64})")


def sections(report: str) -> dict[str, str]:
    if HEADING not in report:
        return {}
    drift = report.split(HEADING, 1)[1]
    found = {}
    for part in re.split(r"^(?=### )", drift, flags=re.MULTILINE)[1:]:
        key = part.split("\n", 1)[0][4:].strip()
        found[key] = part.rstrip("\n") + "\n"
    return found


def fingerprint(body: str) -> str | None:
    match = MARKER.search(body)
    return match[1] if match else None


def decide(key: str, body: str, issues: list[dict]) -> tuple[str, int | None]:
    mine = [i for i in issues if i.get("title") == f"re-vet {key}"]
    seen = fingerprint(body)
    for item in mine:
        if item.get("state") == "OPEN":
            same = bool(seen) and seen in (item.get("body") or "")
            return ("keep" if same else "edit"), item["number"]
    if seen:
        for item in mine:
            if item.get("state") == "CLOSED" and seen in (
                item.get("body") or ""
            ):
                return "skip", item["number"]
    return "create", None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--issues", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    issues = json.loads(args.issues.read_text(encoding="utf-8"))
    report = args.report.read_text(encoding="utf-8")
    for key, body in sections(report).items():
        (args.out / f"body-{key}.md").write_text(body, encoding="utf-8")
        action, number = decide(key, body, issues)
        print(f"{action} {key}" + (f" {number}" if number else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
