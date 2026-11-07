"""Run the packaged fetch_upstream.sh in the current directory."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "fetch_upstream.sh"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    return subprocess.run(["sh", str(SCRIPT), *args], check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
