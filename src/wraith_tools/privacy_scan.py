"""Scan tracked files for private data. Never prints matched text."""

from __future__ import annotations

import argparse
import ipaddress
import os
import re
import subprocess
import sys
from pathlib import Path

SKIP_NAMES = {"uv.lock", ".secrets.baseline"}
ALLOW_MARKER = "privacy-scan: allow"
ALLOWED_DOMAINS = {
    "example.com",
    "example.org",
    "users.noreply.github.com",
}
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
IPV4 = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
HOST = re.compile(r"\b[\w-]+\.ts\.net\b|\b[\w-]+\.local\b(?![.\w-])")
HOME = re.compile(r"/home/[a-z_][\w-]*/|/Users/[\w-]+/|C:\\Users\\")
CREDENTIAL = re.compile(
    r"AKIA[0-9A-Z]{16}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|gh[pousr]_[A-Za-z0-9]{36}"
    r"|sk-ant-[A-Za-z0-9_-]{20,}"
    r"|AIza[0-9A-Za-z_-]{35}"
    r'|"private_key"\s*:'
)
PRIVATE_NETS = [
    ipaddress.ip_network(n)
    for n in (
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "100.64.0.0/10",
    )
]


def _has_email(line: str) -> bool:
    for m in EMAIL.finditer(line):
        if m.group(0) == "git@github.com":
            continue
        if m.group(1).lower() not in ALLOWED_DOMAINS:
            return True
    return False


def _has_private_ip(line: str) -> bool:
    for m in IPV4.finditer(line):
        try:
            ip = ipaddress.ip_address(m.group(0))
        except ValueError:
            continue
        if m.group(0).endswith(".0"):
            continue
        if any(ip in net for net in PRIVATE_NETS):
            return True
    return False


def _kinds(line: str, terms: list[str]) -> list[str]:
    found = []
    if _has_email(line):
        found.append("email")
    if _has_private_ip(line):
        found.append("private-ip")
    if HOST.search(line):
        found.append("internal-host")
    if HOME.search(line):
        found.append("home-path")
    if CREDENTIAL.search(line):
        found.append("credential")
    lower = line.lower()
    if any(t.lower() in lower for t in terms):
        found.append("private-term")
    return found


def scan(files: list[Path], extra_terms: list[str]) -> list[str]:
    findings = []
    for path in files:
        if path.name in SKIP_NAMES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for num, line in enumerate(text.splitlines(), start=1):
            if ALLOW_MARKER in line:
                continue
            for kind in _kinds(line, extra_terms):
                findings.append(f"{path}:{num}: {kind}")
    return findings


def _read_terms(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [
        s for s in (x.strip() for x in lines) if s and not s.startswith("#")
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*")
    args = parser.parse_args(argv).files
    terms: list[str] = []
    terms_env = os.environ.get("WRAITH_PRIVATE_TERMS_FILE")
    if terms_env:
        terms_path = Path(terms_env)
        if not terms_path.is_file():
            print("terms file not found")
            return 2
        terms = _read_terms(terms_path)
    if args:
        files = [Path(a) for a in args]
    else:
        out = subprocess.run(
            ["git", "ls-files"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        files = [Path(p) for p in out.splitlines() if p]
    findings = scan(files, terms)
    for finding in findings:
        print(finding)
    print(f"{len(findings)} findings")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
