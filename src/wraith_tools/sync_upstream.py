"""Merge upstream changes into vendored files and report what needs review."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

COMPANIONS = ("DBT", "GCP", "TF")
# The companion skills wraith names, from the Decision sections of
# docs/adr/0002 to 0004. Drift anywhere else in a vendor repo is out of
# scope: wraith never vetted those skills and never points to them (#91).
# The context-engineering skills named in ADR 0003 live in a repo this
# sync does not fetch, so they are not listed here.
NAMED = {
    "DBT": frozenset(
        {
            "running-dbt-commands",
            "using-dbt-for-analytics-engineering",
            "adding-dbt-unit-test",
            "maintaining-dbt-documentation",
            "building-dbt-semantic-layer",
            "creating-mermaid-dbt-dag",
            "working-with-dbt-mesh",
        }
    ),
    "GCP": frozenset(
        {
            "bigquery-basics",
            "bigquery-optimization",
            "bigquery-troubleshooting",
            "bigquery-observability",
            "bigquery-ai-ml",
            "bigquery-udfs",
            "datalineage-summary",
            "datalineage-bigquery-asset-impact-analysis",
            "cloud-logging-query-generation",
            "dbt-sf-to-bq-translator",
            "bigquery-migration-sql-translator",
            "cloud-run-basics",
            "cloud-build-basics",
            "cloud-run-alert-configuration",
            "google-cloud-slo-alert-configuration",
            "google-cloud-waf-security",
            "iam-helper-for-troubleshooting",
            "iam-helper-for-policy-simulator",
            "iam-helper-for-policy-management",
            "iam-helper-for-privileged-access-management",
            "google-cloud-recipe-auth",
            "google-cloud-waf-reliability",
            "google-cloud-waf-cost-optimization",
            "google-cloud-waf-operational-excellence",
            "gcloud",
        }
    ),
    "TF": frozenset(
        {
            "terraform-style-guide",
            "terraform-test",
            "refactor-module",
            "terraform-search-import",
        }
    ),
}
SKIP_DIRS = {".git", ".upstream", ".venv", "node_modules"}

RISK_PATTERNS = {
    "dbt-full-refresh": r"--full-refresh",
    "terraform-apply": r"\bterraform\s+(apply|destroy)\b",
    "auto-approve": r"auto-approve",
    "pipe-to-shell": r"curl[^\n]*\|\s*(ba)?sh",
    "rm-recursive": r"\brm\s+-\w*r",
    "no-verify": r"--no-verify",
    "telemetry": r"telemetry|analytics",
    "unpinned-launcher": r"\b(npx|uvx)\s+[\w@/.-]+@latest\b",
    "new-url": r"https?://",
}
RISK_RES = {k: re.compile(v) for k, v in RISK_PATTERNS.items()}

ENTRY = re.compile(r"^([A-Z]+)@([0-9a-f]+):(.+)$")
SOURCE_LINE = re.compile(r"^\s*source:\s*(.+?)\s*$")
COMMENT_SOURCE = re.compile(r"^(?:<!--|#)\s*source:\s*(.+?)\s*(?:-->)?\s*$")

Entry = tuple[str, str, str]


def _entries(value: str) -> list[Entry]:
    value = value.strip().strip("\"'")
    found = []
    for part in value.split(","):
        match = ENTRY.match(part.strip())
        if match:
            found.append((match[1], match[2], match[3]))
    return found


def _file_entries(path: Path) -> list[Entry]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (UnicodeDecodeError, OSError):
        return []
    if path.name == "SKILL.md":
        if not lines or lines[0].strip() != "---":
            return []
        for line in lines[1:]:
            if line.strip() == "---":
                break
            match = SOURCE_LINE.match(line)
            if match:
                return _entries(match[1])
        return []
    head = lines[:2] if lines and lines[0].startswith("#!") else lines[:1]
    for line in head[-1:]:
        match = COMMENT_SOURCE.match(line)
        if match:
            return _entries(match[1])
    if path.suffix == ".md":
        fence = next(
            (i for i, ln in enumerate(lines) if ln.startswith("```")), None
        )
        if fence is not None:
            block = lines[fence + 1 : fence + 3]
            if block and block[0].startswith("#!"):
                block = block[1:]
            match = block and COMMENT_SOURCE.match(block[0])
            if match:
                return _entries(match[1])
    return []


def provenance(root: Path) -> dict[str, list[Entry]]:
    found: dict[str, list[Entry]] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if SKIP_DIRS & set(rel.parts) or not path.is_file():
            continue
        entries = _file_entries(path)
        if entries:
            found[rel.as_posix()] = entries
    return found


def merge_file(ours: Path, base: Path, theirs: Path) -> tuple[str, bool]:
    result = subprocess.run(
        ["git", "merge-file", "-p", str(ours), str(base), str(theirs)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode < 0 or result.returncode > 127:
        raise RuntimeError(result.stderr.strip())
    return result.stdout, result.returncode == 0


def risk_scan(diff_text: str) -> list[str]:
    hits = []
    for line in diff_text.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        added = line[1:]
        for label, pattern in RISK_RES.items():
            if pattern.search(added):
                hits.append(f"{label}: {added.strip()}")
    return hits


def _git(directory: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(directory), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _sha(directory: Path) -> str:
    return _git(directory, "rev-parse", "HEAD")


def _ref(directory: Path) -> str:
    return _git(directory, "describe", "--tags", "--exact-match") or "-"


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError, UnicodeDecodeError):
        return None


def _bytes(path: Path) -> bytes | None:
    return path.read_bytes() if path.is_file() else None


def _diff(old: str, new: str, name: str) -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            f"a/{name}",
            f"b/{name}",
        )
    )


@dataclass
class Row:
    path: str
    status: str
    hits: list[str] = field(default_factory=list)


@dataclass
class Drift:
    rows: list[Row]
    fingerprint: str


@dataclass
class Change:
    key: str
    upstream: str
    diff: str


def _sync_file(
    root: Path, rel: str, entries: list[Entry], old: Path, new: Path
) -> tuple[Row | None, Change | None]:
    changed = []
    for key, _sha7, upath in entries:
        before = _read(old / key / upath)
        after = _read(new / key / upath)
        if before is None or before == after:
            continue
        changed.append((key, upath, before, after))
    if not changed:
        return None, None
    key, upath, before, after = changed[0]
    if len(entries) > 1:
        return Row(rel, "composite"), None
    if after is None:
        return Row(rel, "removed"), None
    diff = _diff(before, after, upath)
    hits = risk_scan(diff)
    change = Change(key, upath, diff)
    ours = root / rel
    with tempfile.TemporaryDirectory() as tmp:
        base_file = Path(tmp) / "base"
        theirs_file = Path(tmp) / "theirs"
        base_file.write_text(before, encoding="utf-8")
        theirs_file.write_text(after, encoding="utf-8")
        merged, clean = merge_file(ours, base_file, theirs_file)
    if not clean:
        return Row(rel, "conflict", hits), change
    old7 = entries[0][1]
    new7 = _sha(new / key)[:7]
    merged = merged.replace(f"{key}@{old7}:{upath}", f"{key}@{new7}:{upath}")
    ours.write_text(merged, encoding="utf-8")
    return Row(rel, "clean", hits), change


def _named_dirs(root: Path, key: str) -> set[str]:
    if not root.is_dir():
        return set()
    found = set()
    for path in root.rglob("SKILL.md"):
        rel = path.parent.relative_to(root)
        if ".git" not in rel.parts and rel.name in NAMED[key]:
            found.add(rel.as_posix())
    return found


def _files(root: Path, rel_dir: str) -> set[str]:
    base = root / rel_dir
    if not base.is_dir():
        return set()
    return {
        path.relative_to(root).as_posix()
        for path in base.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(root).parts
    }


def key_drift(key: str, old: Path, new: Path) -> tuple[Drift | None, str]:
    """Drift and the combined diff for one companion's two checkouts.

    Every file in a named skill's folder counts, scripts included. The
    fingerprint hashes the changed files' new content, so it moves only
    when a named skill changes, not when the rest of the repo does (#91).
    """
    dirs = _named_dirs(old, key) | _named_dirs(new, key)
    files: set[str] = set()
    for rel_dir in dirs:
        files |= _files(old, rel_dir) | _files(new, rel_dir)
    rows = []
    diffs = []
    digest = hashlib.sha256()
    for rel in sorted(files):
        before = _bytes(old / rel)
        after = _bytes(new / rel)
        if before == after:
            continue
        if after is None:
            status = "removed"
        elif before is None:
            status = "added"
        else:
            status = "changed"
        diff = _diff(
            (before or b"").decode("utf-8", "replace"),
            (after or b"").decode("utf-8", "replace"),
            rel,
        )
        rows.append(Row(rel, status, risk_scan(diff)))
        diffs.append(diff)
        digest.update(rel.encode() + b"\0")
        digest.update(b"\0removed" if after is None else after)
        digest.update(b"\0")
    if not rows:
        return None, ""
    return Drift(rows, digest.hexdigest()), "".join(diffs)


def _companion_drift(old: Path, new: Path) -> dict[str, Drift]:
    drift: dict[str, Drift] = {}
    for key in COMPANIONS:
        if not (new / key).is_dir():
            continue
        if _sha(old / key) == _sha(new / key):
            continue
        found, _ = key_drift(key, old / key, new / key)
        if found:
            drift[key] = found
    return drift


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def _report(
    pins: list[tuple[str, str, str, str]],
    rows: list[Row],
    changes: dict[str, Change],
    drift: dict[str, Drift],
) -> str:
    out = ["# Upstream sync", "", "| KEY | Old ref | New ref | New SHA |"]
    out.append("|---|---|---|---|")
    for key, old_ref, new_ref, sha in pins:
        out.append(f"| {key} | {old_ref} | {new_ref} | {sha} |")
    out += ["", "| File | Status | Hits |", "|---|---|---|"]
    for row in rows:
        hits = "<br>".join(_cell(h) for h in row.hits)
        out.append(f"| {row.path} | {row.status} | {hits} |")
    for rel, change in changes.items():
        out += [
            "",
            "<details>",
            f"<summary>{change.key}:{change.upstream} ({rel})</summary>",
            "",
            "```diff",
            change.diff.rstrip("\n"),
            "```",
            "",
            "</details>",
        ]
    if drift:
        out += ["", "## Companion drift"]
        for key, found in drift.items():
            out += [
                "",
                f"### {key}",
                "",
                f"<!-- drift-fingerprint: {key} {found.fingerprint} -->",
                (
                    f"Re-vet these changes, then bump the {key} pin in"
                    " upstream-pins.txt and add an addendum to the"
                    " companion ADR. Or close this issue to keep the current"
                    " pin: it stays closed until these files change again."
                ),
                "",
            ]
            for row in found.rows:
                suffix = "" if row.status == "changed" else f" ({row.status})"
                out.append(f"- {row.path}{suffix}")
                out += [f"  - {_cell(h)}" for h in row.hits]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old", type=Path, required=True)
    parser.add_argument("--new", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)

    rows: list[Row] = []
    changes: dict[str, Change] = {}
    blocked: set[str] = set()
    for rel, entries in provenance(args.root).items():
        row, change = _sync_file(args.root, rel, entries, args.old, args.new)
        if row:
            rows.append(row)
            if row.status != "clean":
                blocked.update(key for key, _, _ in entries)
        if change:
            changes[rel] = change
    drift = _companion_drift(args.old, args.new)

    pins = []
    for path in sorted(p for p in args.new.iterdir() if p.is_dir()):
        pins.append(
            (path.name, _ref(args.old / path.name), _ref(path), _sha(path))
        )
    args.report.write_text(
        _report(pins, rows, changes, drift), encoding="utf-8"
    )
    # Pins the workflow may bump: a KEY with any unmerged file keeps its
    # old pin, or the next run would diff from the new one and lose it.
    print(
        " ".join(
            key
            for key, _, _, sha in pins
            if key not in COMPANIONS
            and key not in blocked
            and _sha(args.old / key) != sha
        )
    )

    companion_hits = any(r.hits for d in drift.values() for r in d.rows)
    if any(r.status != "clean" or r.hits for r in rows) or companion_hits:
        return 20
    return 10 if rows else 0


if __name__ == "__main__":
    sys.exit(main())
