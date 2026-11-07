"""Draft a companion re-vet for the owner to accept by merging (#95).

Subcommands, run by the vet and propose jobs in upstream-sync.yml:

- fetch: check out one companion at its pinned SHA, or at --sha.
- bundle: write the named-skill diff and its facts for one companion.
- prompt: print the review prompt with the diff fenced as untrusted.
- verdict: check the model's answer; anything off becomes "unread".
- apply: bump the pin, append the ADR addendum, write the PR body and
  print the PR title. Prints nothing when there is no drift.

The model runs with no tools and never sees a write token. Nothing here
merges anything: the owner's merge is the acceptance.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
from pathlib import Path

from wraith_tools.sync_upstream import NAMED, _sha, key_drift

PROMPT = Path(__file__).resolve().parent / "vet_prompt.md"
ADRS = {
    "DBT": "0002-companion-dbt.md",
    "GCP": "0003-companion-google.md",
    "TF": "0004-companion-hashicorp.md",
}
DIFF_LIMIT = 150_000
BODY_DIFF_LIMIT = 45_000
VERDICTS = ("unchanged", "changed", "block")
CAPS = {"summary": 6, "risks": 10, "conflicts": 10}
TEXT_LIMIT = 300
PIN_LINE = re.compile(r"^(\w+) (\S+) (\S+) ([0-9a-f]{40})$", re.MULTILINE)
SECRETS = re.compile(
    r"sk-ant-[\w-]+|gh[pousr]_\w{20,}|github_pat_\w+"
    r"|-----BEGIN [A-Z ]+-----"
)


def fetch(url: str, sha: str, dest: Path) -> None:
    dest.mkdir(parents=True)

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(dest), *args], check=True)

    git("init", "-q")
    git("remote", "add", "origin", url)
    git("fetch", "-q", "--depth", "1", "origin", sha)
    git("checkout", "-q", "--detach", "FETCH_HEAD")
    if _sha(dest) != sha:
        raise RuntimeError(f"fetched {_sha(dest)}, wanted {sha}")


def pins(text: str) -> dict[str, tuple[str, str, str]]:
    return {m[1]: (m[2], m[3], m[4]) for m in PIN_LINE.finditer(text)}


def bump_pin(text: str, key: str, sha: str) -> str:
    url, _ref, _old = pins(text)[key]
    line = re.compile(rf"^{key} \S+ \S+ [0-9a-f]{{40}}$", re.MULTILINE)
    return line.sub(f"{key} {url} - {sha}", text, count=1)


def _skill(key: str, path: str) -> str:
    for part in reversed(Path(path).parts[:-1]):
        if part in NAMED[key]:
            return part
    return Path(path).parts[0]


def bundle(key: str, old: Path, new: Path, out: Path) -> dict:
    found, diff = key_drift(key, old, new)
    rows = found.rows if found else []
    facts = {
        "key": key,
        "old_sha": _sha(old),
        "new_sha": _sha(new),
        "fingerprint": found.fingerprint if found else None,
        "skills": sorted({_skill(key, r.path) for r in rows}),
        "files": [
            {"path": r.path, "status": r.status, "hits": r.hits} for r in rows
        ],
        "truncated": len(diff) > DIFF_LIMIT,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "facts.json").write_text(json.dumps(facts, indent=1) + "\n")
    (out / "diff.patch").write_text(diff, encoding="utf-8")
    return facts


def _load(bundle_dir: Path) -> tuple[dict, str]:
    facts = json.loads((bundle_dir / "facts.json").read_text())
    diff = (bundle_dir / "diff.patch").read_text(encoding="utf-8")
    return facts, diff


def prompt(bundle_dir: Path) -> str:
    facts, diff = _load(bundle_dir)
    nonce = (facts["fingerprint"] or "none")[:16]
    files = "\n".join(f"- {f['status']}: {f['path']}" for f in facts["files"])
    return (
        PROMPT.read_text(encoding="utf-8")
        + f"\nCompanion: {facts['key']}. Skills: "
        + ", ".join(facts["skills"])
        + f".\nFiles:\n{files}\n\n"
        + f"BEGIN UNTRUSTED DIFF {nonce}\n"
        + diff[:DIFF_LIMIT]
        + f"\nEND UNTRUSTED DIFF {nonce}\n\n"
        + "Answer now with the JSON object only.\n"
    )


def sanitize(text: str) -> str:
    text = SECRETS.sub("[redacted]", text)
    text = text.replace("@", "(at)").replace("```", "'''")
    text = text.replace("<", "&lt;").replace(">", "&gt;")
    text = text.replace("\u2014", "-").replace("–", "-")
    text = " ".join(text.split())
    if len(text) > TEXT_LIMIT:
        text = text[: TEXT_LIMIT - 3] + "..."
    return text


def _unread(note: str) -> dict:
    return {
        "verdict": "unread",
        "summary": [],
        "risks": [],
        "conflicts": [],
        "note": note,
    }


def _object(raw: str) -> object:
    try:
        outer = json.loads(raw)
    except json.JSONDecodeError:
        outer = {"result": raw}
    if not isinstance(outer, dict):
        return None
    if outer.get("is_error"):
        return None
    if isinstance(outer.get("structured_output"), dict):
        return outer["structured_output"]
    text = outer.get("result")
    if not isinstance(text, str):
        return None
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def parse_verdict(raw: str, facts: dict) -> dict:
    if facts.get("truncated"):
        return _unread("the diff was too large to read whole")
    found = _object(raw)
    if not isinstance(found, dict):
        return _unread("no usable answer from the machine read")
    if found.get("verdict") not in VERDICTS:
        return _unread("the answer had no valid verdict")
    verdict = {"verdict": found["verdict"]}
    for field, cap in CAPS.items():
        items = found.get(field)
        if not isinstance(items, list) or not all(
            isinstance(i, str) for i in items
        ):
            return _unread(f"the answer's {field} was not a list of text")
        verdict[field] = [sanitize(i) for i in items[:cap] if i.strip()]
    if not verdict["summary"]:
        return _unread("the answer had no summary")
    return verdict


def _hits(facts: dict) -> list[str]:
    return [f"{f['path']}: {h}" for f in facts["files"] for h in f["hits"]]


def addendum(facts: dict, verdict: dict, ticket: int, date: str) -> str:
    key, old, new = facts["key"], facts["old_sha"], facts["new_sha"]
    skills = ", ".join(f"`{s}`" for s in facts["skills"])
    labels = sorted(
        {h.split(":", 1)[0] for f in facts["files"] for h in f["hits"]}
    )
    scan = (
        f"{len(_hits(facts))} risk hits ({', '.join(labels)})"
        if labels
        else "no risk hits"
    )
    out = [
        f"## Addendum {date}: pin bumped to {new[:7]}",
        "",
        f"Ticket: WSK-{ticket:05d}. Drafted by the nightly upstream sync",
        f"(#95). The {key} pin moves from {old[:7]} to",
        f"{new}. Named skills changed: {skills}.",
        f"Files changed: {len(facts['files'])}. Automated scan: {scan}.",
        "",
    ]
    if verdict["verdict"] == "unread":
        out += [
            f"No machine read ({verdict['note']}),",
            "so a human must read the diff in the pull request before",
            "accepting it.",
        ]
    else:
        out.append(
            f"Machine read, verdict {verdict['verdict']} (a model with no "
            "tools, given only the diff):"
        )
        out += [f"- {s}" for s in verdict["summary"]]
        for field, label in (("risks", "Risks"), ("conflicts", "Conflicts")):
            if verdict[field]:
                out += ["", f"{label}:"] + [f"- {s}" for s in verdict[field]]
    out += [
        "",
        "The owner accepts the bump by merging it, after reading the diff in",
        "the pull request.",
    ]
    return "\n".join(out) + "\n"


def title(facts: dict, ticket: int) -> str:
    return (
        f"\U0001f47b chore/WSK-{ticket:05d}: re-vet {facts['key']}"
        f" and pin {facts['new_sha'][:7]}"
    )


def _fence(text: str) -> str:
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def pr_body(facts: dict, verdict: dict, ticket: int, diff: str) -> str:
    shown = diff
    if len(shown) > BODY_DIFF_LIMIT:
        shown = shown[:BODY_DIFF_LIMIT] + "\n... diff truncated ...\n"
    fence = _fence(shown)
    read = verdict["verdict"]
    lines = [
        f"Closes #{ticket}.",
        "",
        (
            "Drafted by the nightly upstream sync (#95). **Not merged"
            " automatically: merging is the owner's acceptance of this"
            " re-vet.**"
        ),
        "",
        "| | |",
        "|---|---|",
        f"| Companion | {facts['key']} |",
        f"| Pin | `{facts['old_sha'][:7]}` to `{facts['new_sha'][:7]}` |",
        "| Named skills changed | "
        + ", ".join(f"`{s}`" for s in facts["skills"])
        + " |",
        f"| Risk hits | {len(_hits(facts))} |",
        f"| Machine read | {read} |",
        "",
        "## Machine read",
        "",
    ]
    if read == "unread":
        lines.append(f"None: {verdict['note']}. Read the diff below.")
    else:
        lines += [f"- {s}" for s in verdict["summary"]]
        for field, label in (("risks", "Risks"), ("conflicts", "Conflicts")):
            if verdict[field]:
                lines += ["", f"**{label}**", ""]
                lines += [f"- {s}" for s in verdict[field]]
    hits = _hits(facts)
    if hits:
        lines += ["", "## Risk hits", ""]
        lines += [f"- {sanitize(h)}" for h in hits[:30]]
    lines += [
        "",
        "## Diff",
        "",
        "<details>",
        f"<summary>{len(facts['files'])} files</summary>",
        "",
        f"{fence}diff",
        shown.rstrip("\n"),
        fence,
        "",
        "</details>",
        "",
        (
            "The machine read had no tools: it saw only this diff as text,"
            " and could not read files, run commands or reach the network."
        ),
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p_fetch = sub.add_parser("fetch")
    p_fetch.add_argument("--key", required=True)
    p_fetch.add_argument("--sha")
    p_fetch.add_argument("--dest", type=Path, required=True)
    p_fetch.add_argument(
        "--pins", type=Path, default=Path.cwd() / "upstream-pins.txt"
    )
    p_bundle = sub.add_parser("bundle")
    p_bundle.add_argument("--key", required=True)
    p_bundle.add_argument("--old", type=Path, required=True)
    p_bundle.add_argument("--new", type=Path, required=True)
    p_bundle.add_argument("--out", type=Path, required=True)
    p_prompt = sub.add_parser("prompt")
    p_prompt.add_argument("--bundle", type=Path, required=True)
    p_verdict = sub.add_parser("verdict")
    p_verdict.add_argument("--bundle", type=Path, required=True)
    p_verdict.add_argument("--raw", type=Path, required=True)
    p_apply = sub.add_parser("apply")
    p_apply.add_argument("--bundle", type=Path, required=True)
    p_apply.add_argument("--ticket", type=int, required=True)
    p_apply.add_argument("--root", type=Path, required=True)
    p_apply.add_argument("--pr-body", type=Path, required=True)
    p_apply.add_argument("--date", default=str(datetime.date.today()))
    args = parser.parse_args(argv)

    if args.command == "fetch":
        url, _ref, pinned = pins(args.pins.read_text(encoding="utf-8"))[
            args.key
        ]
        fetch(url, args.sha or pinned, args.dest)
    elif args.command == "bundle":
        bundle(args.key, args.old, args.new, args.out)
    elif args.command == "prompt":
        print(prompt(args.bundle), end="")
    elif args.command == "verdict":
        facts, _ = _load(args.bundle)
        raw = args.raw.read_text(encoding="utf-8") if args.raw.exists() else ""
        verdict = parse_verdict(raw, facts)
        (args.bundle / "verdict.json").write_text(json.dumps(verdict) + "\n")
    else:
        facts, diff = _load(args.bundle)
        if not facts["files"]:
            return 0
        verdict = json.loads((args.bundle / "verdict.json").read_text())
        fetch_sh = args.root / "upstream-pins.txt"
        fetch_sh.write_text(
            bump_pin(fetch_sh.read_text(), facts["key"], facts["new_sha"])
        )
        adr = args.root / "docs" / "adr" / ADRS[facts["key"]]
        text = adr.read_text(encoding="utf-8").rstrip("\n")
        note = addendum(facts, verdict, args.ticket, args.date)
        adr.write_text(f"{text}\n\n{note}", encoding="utf-8")
        args.pr_body.write_text(
            pr_body(facts, verdict, args.ticket, diff), encoding="utf-8"
        )
        print(title(facts, args.ticket))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
