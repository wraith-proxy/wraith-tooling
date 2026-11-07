"""Run the plugin content checks against the repo in the cwd."""

from __future__ import annotations

import argparse
import sys

import pytest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, epilog="Extra arguments go to pytest."
    )
    _, args = parser.parse_known_args(argv)
    return int(
        pytest.main(
            [
                "--pyargs",
                "wraith_tools.plugin_checks",
                "-q",
                "-p",
                "no:cacheprovider",
                *args,
            ]
        )
    )


if __name__ == "__main__":
    sys.exit(main())
