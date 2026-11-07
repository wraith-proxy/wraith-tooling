import subprocess

import pytest

from wraith_tools import file_types

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 8


@pytest.fixture
def repo(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.chdir(tmp_path)

    def add(name, data):
        (tmp_path / name).write_bytes(data)
        subprocess.run(["git", "add", name], cwd=tmp_path, check=True)

    return add


def test_clean_pass(repo, capsys):
    repo("a.md", b"hello\n")
    repo("LICENSE", b"MIT\n")
    repo(".gitignore", b"x\n")
    repo("i.png", PNG)
    repo("w.webp", b"RIFF1234WEBPxx")
    assert file_types.main([]) == 0
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "name,data,reason",
    [
        ("a.py", b"x = 1\n", "not allowed"),
        ("a.md", b"#!/bin/sh\n", "shebang"),
        ("a.txt", b"\xff\xfe\xfa", "UTF-8"),
        ("a.txt", b"ab\x00cd", "NUL"),
        ("a.png", b"GIF89a", "magic"),
        ("a.webp", b"RIFF1234WAVE", "magic"),
        ("package.json", b"{}\n", "package manager"),
        ("pyproject.toml", b"\n", "package manager"),
        ("requirements-dev.txt", b"x\n", "package manager"),
    ],
)
def test_failures(repo, capsys, name, data, reason):
    repo(name, data)
    assert file_types.main([]) == 1
    out = capsys.readouterr().out
    assert out.startswith(f"{name}: ") and reason in out


def test_deleted_file_skipped(repo, tmp_path):
    repo("a.md", b"x\n")
    (tmp_path / "a.md").unlink()
    assert file_types.main([]) == 0


@pytest.mark.parametrize("mod", ["file_types", "check_plugin"])
def test_help(mod, capsys):
    import importlib

    m = importlib.import_module(f"wraith_tools.{mod}")
    with pytest.raises(SystemExit) as e:
        m.main(["--help"])
    assert e.value.code == 0
