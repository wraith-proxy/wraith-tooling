"""Lint skills/ and agents/ against the wraith repository rules."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import yaml

SKILL_KEYS = {
    "name",
    "description",
    "license",
    "compatibility",
    "metadata",
    "allowed-tools",
}
AGENT_KEYS = {"name", "description", "model", "tools"}
MODELS = {"opus", "sonnet", "haiku"}
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
SOURCE_RE = re.compile(r"^(SP|MP|KA|AA|GS)@[0-9a-f]{7}:\S+$")
LINK_RE = re.compile(r"\]\(([^)\s]+)\)")
WRAITH_RE = re.compile(r"wraith:([a-z0-9]+(?:-[a-z0-9]+)*)")
EM_DASH = chr(0x2014)
UPSTREAM_TOKENS = (
    "superpowers:",
    "docs/superpowers",
    ".gstack",
    "gstack-",
    "setup-matt-pocock-skills",
    "ask-matt",
    "office-hours",
)
REPORT_HEADING = "## When you finish, report"
EM_DASH_DIRS = ("skills", "agents", "hooks", "evals")
EM_DASH_FILES = ("README.md", "AGENTS.md", "PLAN.md")
SKIP_DIRS = {".git", ".venv", ".upstream"}
MAX_FILE_BYTES = 256 * 1024
MAX_FILES = 480
MAX_SKILLS = 30


def split_frontmatter(text):
    """Return (frontmatter text, body) or (None, text)."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[1:i]), "\n".join(lines[i + 1 :])
    return None, text


def parse_frontmatter(text):
    """Return (mapping or None, body, error message or None)."""
    raw, body = split_frontmatter(text)
    if raw is None:
        return None, body, "missing frontmatter"
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError:
        return None, body, "frontmatter is not valid YAML"
    if not isinstance(data, dict):
        return None, body, "frontmatter is not a mapping"
    return data, body, None


def read_text(path):
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def walk_files(root):
    """Yield every non-symlink file path, skipping excluded dirs."""
    for dirpath, dirnames, filenames in os.walk(root):
        rel = Path(dirpath).relative_to(root)
        dirnames[:] = [
            d
            for d in dirnames
            if d not in SKIP_DIRS
            and rel.parts + (d,) != ("evals", "results")
            and "__pycache__" != d
        ]
        for name in filenames:
            yield Path(dirpath) / name


def notice_keys(root):
    text = read_text(root / "THIRD_PARTY_NOTICES.md") or ""
    return set(re.findall(r"^#+\s+(\w+)\s*$", text, re.MULTILINE))


def check_skill(root, sdir, notices, out):
    md = sdir / "SKILL.md"
    rel = md.relative_to(root).as_posix()
    if not md.is_file():
        out.append(f"{sdir.relative_to(root).as_posix()}: L1 missing SKILL.md")
        return
    text = md.read_text(encoding="utf-8")
    if text.count("\n") + (not text.endswith("\n")) > 400:
        out.append(f"{rel}: L8 more than 400 lines")
    if len(text.encode("utf-8")) > 20000:
        out.append(f"{rel}: L8 more than 20000 bytes")
    fm, _, err = parse_frontmatter(text)
    if fm is None:
        out.append(f"{rel}: L2 {err}")
        return
    extra = sorted(set(map(str, fm)) - SKILL_KEYS)
    if extra:
        out.append(f"{rel}: L3 unsupported keys {', '.join(extra)}")
    name = fm.get("name")
    if not isinstance(name, str) or not NAME_RE.match(name):
        out.append(f"{rel}: L4 name is not lowercase hyphenated")
    elif len(name) > 64:
        out.append(f"{rel}: L4 name longer than 64 characters")
    elif name != sdir.name:
        out.append(f"{rel}: L4 name does not equal directory name")
    desc = fm.get("description")
    if not isinstance(desc, str) or not 1 <= len(desc) <= 400:
        out.append(f"{rel}: L5 description must be 1 to 400 characters")
    compat = fm.get("compatibility")
    if compat is not None and (
        not isinstance(compat, str) or len(compat) > 500
    ):
        out.append(f"{rel}: L6 compatibility over 500 characters")
    meta = fm.get("metadata")
    if meta is not None and not (
        isinstance(meta, dict)
        and all(
            isinstance(k, str) and isinstance(v, str) for k, v in meta.items()
        )
    ):
        out.append(f"{rel}: L6 metadata must map strings to strings")
    if fm.get("license") != "MIT":
        out.append(f"{rel}: L7 license must be MIT")
    check_source(rel, meta, notices, out)


def check_source(rel, meta, notices, out):
    source = meta.get("source") if isinstance(meta, dict) else None
    if not isinstance(source, str):
        out.append(f"{rel}: L7 metadata.source is required")
        return
    if source == "new":
        return
    for part in (p.strip() for p in source.split(",")):
        if not SOURCE_RE.match(part):
            out.append(f"{rel}: L7 bad metadata.source entry '{part}'")
        elif part.split("@")[0] not in notices:
            out.append(f"{rel}: L7 {part.split('@')[0]} not in notices")


def check_links(root, sdir, out):
    for path in sorted(sdir.rglob("*.md")):
        text = read_text(path)
        if text is None:
            continue
        for target in LINK_RE.findall(text):
            if re.match(r"^([a-z][a-z0-9+.-]*:|#)", target, re.IGNORECASE):
                continue
            dest = (path.parent / target.split("#")[0]).resolve()
            if not dest.is_file() or sdir.resolve() not in dest.parents:
                rel = path.relative_to(root).as_posix()
                out.append(f"{rel}: L9 unresolved link {target}")


def check_agent(root, path, out):
    rel = path.relative_to(root).as_posix()
    text = path.read_text(encoding="utf-8")
    fm, body, err = parse_frontmatter(text)
    if fm is None:
        out.append(f"{rel}: L2 {err}")
        return
    extra = sorted(set(map(str, fm)) - AGENT_KEYS)
    if extra:
        out.append(f"{rel}: L12 unsupported keys {', '.join(extra)}")
    if fm.get("name") != path.stem:
        out.append(f"{rel}: L12 name does not equal file stem")
    if fm.get("model") not in MODELS:
        out.append(f"{rel}: L12 model must be opus, sonnet or haiku")
    desc = fm.get("description")
    if isinstance(desc, str) and len(desc) > 400:
        out.append(f"{rel}: L12 description over 400 characters")
    if len(body.strip("\n").split("\n")) > 120:
        out.append(f"{rel}: L12 body over 120 lines")
    if REPORT_HEADING not in body:
        out.append(f"{rel}: L12 missing '{REPORT_HEADING}'")


def upstream_scope(root):
    """Yield (path, text to scan for upstream tokens)."""
    for path in sorted((root / "skills").rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        text = read_text(path)
        if text is None:
            continue
        if path.name == "SKILL.md" and path.parent.parent.name == "skills":
            text = split_frontmatter(text)[1]
        yield path, text
    for path in sorted((root / "agents").glob("*.md")):
        text = read_text(path)
        if text is not None:
            body = split_frontmatter(text)[1]
            keep = [ln for ln in body.split("\n") if "<!-- source:" not in ln]
            yield path, "\n".join(keep)
    for path in sorted((root / "hooks").rglob("*")):
        text = None if path.is_symlink() else read_text(path)
        if path.is_file() and text is not None:
            yield path, text


def check_text_rules(root, skills, agents, out):
    known = {d.name for d in skills} | {a.stem for a in agents}
    for sub in ("skills", "agents", "hooks"):
        for path in sorted((root / sub).rglob("*")):
            text = read_text(path) if path.is_file() else None
            if text is None or "__pycache__" in path.parts:
                continue
            rel = path.relative_to(root).as_posix()
            for name in sorted(set(WRAITH_RE.findall(text))):
                if name not in known:
                    out.append(f"{rel}: L10 unresolved wraith:{name}")
    em_paths = []
    for sub in EM_DASH_DIRS:
        em_paths += [p for p in (root / sub).rglob("*") if p.is_file()]
    em_paths += [root / n for n in EM_DASH_FILES if (root / n).is_file()]
    for path in sorted(em_paths):
        if EM_DASH in (read_text(path) or ""):
            rel = path.relative_to(root).as_posix()
            out.append(f"{rel}: L11 contains em dash")
    for path, text in upstream_scope(root):
        for token in UPSTREAM_TOKENS:
            if token in text:
                rel = path.relative_to(root).as_posix()
                out.append(f"{rel}: L13 upstream token '{token}'")


def check_tree(root, out):
    count = 0
    for path in walk_files(root):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            out.append(f"{rel}: L15 symlink")
            continue
        count += 1
        if path.stat().st_size > MAX_FILE_BYTES:
            out.append(f"{rel}: L14 larger than 256 KiB")
    if count > MAX_FILES:
        out.append(f".: L14 {count} files (max {MAX_FILES})")
    if (root / "bin").is_dir() and not (root / "bin").is_symlink():
        out.append("bin: L15 top-level bin directory")


def lint(root):
    root = Path(root)
    out = []
    sroot = root / "skills"
    skills = (
        sorted(d for d in sroot.iterdir() if d.is_dir())
        if sroot.is_dir()
        else []
    )
    aroot = root / "agents"
    agents = sorted(aroot.glob("*.md")) if aroot.is_dir() else []
    notices = notice_keys(root)
    for sdir in skills:
        check_skill(root, sdir, notices, out)
        check_links(root, sdir, out)
    for agent in agents:
        check_agent(root, agent, out)
    if len(skills) > MAX_SKILLS:
        out.append(f"skills: L16 {len(skills)} skills (max {MAX_SKILLS})")
    check_text_rules(root, skills, agents, out)
    check_tree(root, out)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=None)
    ns = parser.parse_args(argv)
    root = ns.root or Path.cwd()
    problems = lint(root)
    for problem in problems:
        print(problem)
    print(f"{len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
