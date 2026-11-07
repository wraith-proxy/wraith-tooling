import io
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from commitizen.version_increment import VersionIncrement

from wraith_tools.release_gate import increment, load_rules, main

CONFIG = Path(__file__).resolve().parent / "cz.yaml"
GHOST = "\U0001f47b"
RULES = load_rules(CONFIG)


def subject(kind, summary="add the thing"):
    return f"{GHOST} {kind}/WSK-00078: {summary}"


def gate(*subjects):
    return increment(list(subjects), *RULES)


@pytest.mark.parametrize("kind", ["docs", "chore", "ci", "test", "refactor"])
def test_non_releasing_types_do_not_release(kind):
    assert gate(subject(kind)) == "NONE"


@pytest.mark.parametrize(
    "summary",
    [
        "fix the README",
        "feat flag cleanup",
        "document the new feature",
        "close bug 12",
        "fix, feat, feature, bug and break",
        "fix/WSK-00001: nested type in the summary",
        f"{GHOST} feature/WSK-00002: quoted subject",
    ],
)
@pytest.mark.parametrize("kind", ["docs", "chore"])
def test_releasing_words_in_a_non_releasing_subject_do_not_release(
    kind, summary
):
    assert gate(subject(kind, summary)) == "NONE"


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("fix", "PATCH"),
        ("bug", "PATCH"),
        ("feature", "MINOR"),
        ("break", "MINOR"),
    ],
)
def test_releasing_types_bump_by_their_level(kind, expected):
    assert gate(subject(kind)) == expected


def test_break_is_major_once_major_version_zero_is_off(tmp_path):
    cz = yaml.safe_load(CONFIG.read_text())
    cz["commitizen"]["major_version_zero"] = False
    config = tmp_path / ".cz.yaml"
    config.write_text(yaml.safe_dump(cz, allow_unicode=True))
    assert increment([subject("break")], *load_rules(config)) == "MAJOR"


@pytest.mark.parametrize(
    "line",
    [
        ":ghost: chore: release v0.5.11 -> v0.5.12 [skip ci]",
        f'Revert "{GHOST} fix/WSK-00029: real fix"',
        "fix: conventional subject",
        "fix/WSK-00001: no ghost",
        f"{GHOST} feat/WSK-00001: feat is not a type",
        f"{GHOST} fix/WSK-1: short ticket",
        "",
    ],
)
def test_lines_outside_the_releasing_format_do_not_release(line):
    assert gate(line) == "NONE"


def test_highest_subject_wins():
    assert gate(subject("docs"), subject("fix")) == "PATCH"
    assert gate(subject("fix"), subject("feature")) == "MINOR"


def test_no_subjects_is_none():
    assert gate() == "NONE"


def test_only_the_first_line_of_an_entry_counts():
    body = subject("docs") + "\n\n" + subject("break", "phantom")
    assert gate(body) == "NONE"


def test_main_defaults_to_cz_yaml_in_cwd(tmp_path, monkeypatch, capsys):
    (tmp_path / ".cz.yaml").write_text(CONFIG.read_text())
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO(subject("fix") + "\n"))
    assert main([]) == 0
    assert capsys.readouterr().out == "PATCH\n"


def test_main_reads_stdin_and_prints_increment(monkeypatch, capsys):
    stdin = io.StringIO(subject("docs") + "\n" + subject("fix") + "\n")
    monkeypatch.setattr(sys, "stdin", stdin)
    assert main(["--config", str(CONFIG)]) == 0
    assert capsys.readouterr().out == "PATCH\n"


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def test_issue_78_body_line_does_not_release_or_inflate(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    git(repo, "commit", "-q", "--allow-empty", "-m", "base")
    git(repo, "tag", "v0.0.1")
    phantom = subject("break", "phantom line in a body")
    git(
        repo,
        *("commit", "-q", "--allow-empty"),
        *("-m", subject("docs", "tidy"), "-m", phantom),
    )
    log = git(repo, "log", "--format=%s", "v0.0.1..HEAD")
    assert run_cli(log) == "NONE"
    git(repo, "commit", "-q", "--allow-empty", "-m", subject("fix"))
    log = git(repo, "log", "--format=%s", "v0.0.1..HEAD")
    assert run_cli(log) == "PATCH"
    full = git(repo, "log", "--format=%B%x00", "v0.0.1..HEAD")
    messages = [m.strip() for m in full.split("\0") if m.strip()]
    pattern, bump_map, _ = RULES
    commitizen_alone = VersionIncrement.get_highest_by_messages(
        messages, pattern, bump_map
    )
    assert commitizen_alone == VersionIncrement.MAJOR


def run_cli(text):
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "wraith_tools.release_gate",
            "--config",
            str(CONFIG),
        ],
        input=text,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
