"""Pick the release increment from commit subjects alone.

commitizen runs bump_pattern on every line of every commit message, so a
docs, chore or ci commit with a releasing-format line in its body cuts a
release (issue #78). This gate reads subjects only, one per line on stdin,
and prints NONE, PATCH, MINOR or MAJOR using the bump rules in .cz.yaml.
The release workflow passes that to `cz bump --increment`, so no commit
body can start or inflate a release.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml
from commitizen.version_increment import VersionIncrement


def load_rules(path: Path) -> tuple[str, dict[str, str], bool]:
    cz = yaml.safe_load(path.read_text())["commitizen"]
    custom = cz["customize"]
    return (
        custom["bump_pattern"],
        custom["bump_map"],
        bool(cz.get("major_version_zero")),
    )


def increment(
    subjects: list[str],
    pattern: str,
    bump_map: dict[str, str],
    major_version_zero: bool,
) -> str:
    firsts = [s.splitlines()[0] for s in subjects if s.strip()]
    found = VersionIncrement.get_highest_by_messages(firsts, pattern, bump_map)
    if found == VersionIncrement.MAJOR and major_version_zero:
        found = VersionIncrement.MINOR
    return found.name


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=None)
    args = parser.parse_args(argv)
    args.config = args.config or Path.cwd() / ".cz.yaml"
    pattern, bump_map, zero = load_rules(args.config)
    subjects = sys.stdin.read().splitlines()
    print(increment(subjects, pattern, bump_map, zero))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
