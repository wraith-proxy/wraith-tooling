import subprocess
import sys

import pytest

from wraith_tools.sync_commit_type import commit_type


def test_empty_diff_is_chore():
    assert commit_type([]) == "chore"


@pytest.mark.parametrize(
    "path",
    [
        "upstream-pins.txt",
        "scripts/x.py",
        "tests/x.py",
        "evals/x",
        "docs/x.md",
        ".github/workflows/ci.yml",
        "pyproject.toml",
        "uv.lock",
        ".cz.yaml",
    ],
)
def test_non_shipped_path_is_chore(path):
    assert commit_type([path]) == "chore"


@pytest.mark.parametrize(
    "path",
    [
        "skills/x/SKILL.md",
        "agents/a.md",
        "hooks/guard.py",
        "assets/example.txt",
        "com.github.copilot/agents/a.md",
        ".claude-plugin/plugin.json",
        "plugin.json",
        "README.md",
    ],
)
def test_shipped_path_is_fix(path):
    assert commit_type([path]) == "fix"


def test_mix_of_chore_and_fix_paths_is_fix():
    paths = ["upstream-pins.txt", "uv.lock", "skills/x/SKILL.md"]
    assert commit_type(paths) == "fix"


def test_cli_reads_stdin_paths_and_prints_type():
    def run(text):
        return subprocess.run(
            [sys.executable, "-m", "wraith_tools.sync_commit_type"],
            input=text,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    assert run("") == "chore"
    assert run("uv.lock\nscripts/a.py\n") == "chore"
    assert run("uv.lock\nskills/x/SKILL.md\n") == "fix"
