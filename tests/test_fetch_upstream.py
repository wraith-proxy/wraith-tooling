import os
import subprocess

from wraith_tools import fetch_upstream

SCRIPT = fetch_upstream.SCRIPT

CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def git(cwd, *args):
    return subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.com",
            "-C",
            str(cwd),
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
        env=CLEAN_ENV,
    ).stdout.strip()


def run_new_dir(tmp_path, pin):
    pins = tmp_path / "pins"
    pins.write_text(f"X file://{tmp_path / 'up'} - {pin}\n")
    subprocess.run(
        ["sh", str(SCRIPT), "--new-dir", str(tmp_path / "new")],
        check=True,
        capture_output=True,
        env={"PATH": "/usr/bin:/bin", "PINS_FILE": str(pins)},
    )
    return git(tmp_path / "new" / "X", "rev-parse", "HEAD")


def make_repo(tmp_path):
    up = tmp_path / "up"
    up.mkdir()
    git(up, "init", "-q", "-b", "main")
    git(up, "commit", "-q", "--allow-empty", "-m", "one")
    git(up, "tag", "v1.0.0")
    git(up, "commit", "-q", "--allow-empty", "-m", "two")
    return up


def test_tag_older_than_pin_uses_head(tmp_path):
    up = make_repo(tmp_path)
    head = git(up, "rev-parse", "HEAD")
    assert run_new_dir(tmp_path, head) == head


def test_tag_newer_than_pin_uses_tag(tmp_path):
    up = make_repo(tmp_path)
    old = git(up, "rev-parse", "v1.0.0")
    git(up, "tag", "v2.0.0")
    assert run_new_dir(tmp_path, old) == git(up, "rev-parse", "v2.0.0")
