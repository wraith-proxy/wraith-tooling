import os
import subprocess

import pytest

from wraith_tools import privacy_scan
from wraith_tools.privacy_scan import main, scan

AT = "@"


def write(tmp_path, text, name="f.txt"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def kinds(findings):
    return [f.rsplit(": ", 1)[1] for f in findings]


def test_detects_email_and_allows_example_domains(tmp_path):
    bad = "jane.doe" + AT + "corp" + ".io"
    ok1 = "a" + AT + "example" + ".com"
    ok2 = "a" + AT + "example" + ".org"
    ok3 = "1+bob" + AT + "users.noreply" + ".github.com"
    ok4 = "git" + AT + "github" + ".com"
    path = write(tmp_path, f"{bad}\n{ok1}\n{ok2}\n{ok3}\n{ok4}")
    findings = scan([path], [])
    assert findings == [f"{path}:1: email"]


def test_detects_private_ip_allows_public_and_loopback(tmp_path):
    lines = [
        "10." + "1.2.3",
        "172." + "16.5.9",
        "192." + "168.1.20",
        "100." + "64.1.2",
        "8." + "8.8.8",
        "127." + "0.0.1",
        "172." + "32.1.1",
        "999." + "1.1.1",
    ]
    path = write(tmp_path, "\n".join(lines))
    findings = scan([path], [])
    assert kinds(findings) == ["private-ip"] * 4
    assert [f.split(":")[-2] for f in findings] == ["1", "2", "3", "4"]


def test_network_addresses_not_flagged(tmp_path):
    text = "10." + "0.0.0\n192." + "168.1.0\n172." + "16.0.0"
    assert scan([write(tmp_path, text)], []) == []


def test_settings_local_json_not_flagged(tmp_path):
    path = write(tmp_path, "see settings" + ".local" + ".json here")
    assert scan([path], []) == []
    host = write(tmp_path, "box" + ".local" + " up\nnode" + ".ts" + ".net")
    assert kinds(scan([host], [])) == ["internal-host"] * 2


def test_detects_home_path(tmp_path):
    lines = [
        "/ho" + "me/alice/code",
        "/Us" + "ers/bob/code",
        "C:" + "\\" + "Users" + "\\" + "carol",
        "/home" + "/",
    ]
    findings = scan([write(tmp_path, "\n".join(lines))], [])
    assert kinds(findings) == ["home-path"] * 3


def test_detects_credential_patterns(tmp_path):
    lines = [
        "AK" + "IA" + "A" * 16,
        "-----BEGIN " + "RSA PRIVATE KEY-----",
        "gh" + "p_" + "a" * 36,
        "sk-" + "ant-" + "a" * 20,
        "AI" + "za" + "a" * 35,
        '"private' + '_key"' + ": 1",
        "nothing here",
    ]
    findings = scan([write(tmp_path, "\n".join(lines))], [])
    assert kinds(findings) == ["credential"] * 6


def test_extra_terms_case_insensitive(tmp_path):
    path = write(tmp_path, "Hello AcMeCorp world\nclean")
    findings = scan([path], ["acmecorp"])
    assert findings == [f"{path}:1: private-term"]


def test_missing_terms_file_exits_2(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(
        "WRAITH_PRIVATE_TERMS_FILE", str(tmp_path / "absent.txt")
    )
    assert main([str(write(tmp_path, "x"))]) == 2
    assert "terms file not found" in capsys.readouterr().out


def test_terms_file_skips_blank_and_comments(tmp_path, monkeypatch, capsys):
    terms = write(tmp_path, "# note\n\nsecretword\n", "terms.txt")
    monkeypatch.setenv("WRAITH_PRIVATE_TERMS_FILE", str(terms))
    target = write(tmp_path, "a secretword b\nnote\n")
    assert main([str(target)]) == 1
    out = capsys.readouterr().out
    assert f"{target}:1: private-term" in out
    assert out.strip().endswith("1 findings")


def test_allow_marker_skips_line(tmp_path):
    bad = "10." + "1.2.3"
    path = write(tmp_path, bad + " privacy-scan: allow\n" + bad)
    assert scan([path], []) == [f"{path}:2: private-ip"]


def test_output_never_contains_matched_text(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("WRAITH_PRIVATE_TERMS_FILE", raising=False)
    email = "zed" + AT + "corp" + ".io"
    ip = "10." + "9.8.7"
    path = write(tmp_path, email + "\n" + ip + "\n")
    assert main([str(path)]) == 1
    out = capsys.readouterr().out
    assert "zed" not in out and ip not in out and "corp" not in out
    assert out.strip().endswith("2 findings")


def test_clean_run_returns_zero(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("WRAITH_PRIVATE_TERMS_FILE", raising=False)
    assert main([str(write(tmp_path, "hello"))]) == 0
    assert capsys.readouterr().out.strip() == "0 findings"


def test_skips_lockfiles_and_binary(tmp_path):
    bad = "10." + "1.2.3"
    lock = write(tmp_path, bad, "uv.lock")
    base = write(tmp_path, bad, ".secrets.baseline")
    binary = tmp_path / "b.bin"
    binary.write_bytes(b"\xff\xfe" + bad.encode())
    assert scan([lock, base, binary], []) == []


def test_no_args_scans_git_ls_files(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("WRAITH_PRIVATE_TERMS_FILE", raising=False)
    # git hooks export GIT_INDEX_FILE; in a worktree it is absolute and
    # would point the tmp repo's git add at the real index.
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)
    write(tmp_path, "10." + "1.2.3", "tracked.txt")
    subprocess.run(["git", "init", "-q"], check=True)
    subprocess.run(["git", "add", "tracked.txt"], check=True)
    assert privacy_scan.main([]) == 1
    assert "tracked.txt:1: private-ip" in capsys.readouterr().out


@pytest.mark.parametrize("value", ["1.2.3", "300.1.1.1"])
def test_invalid_ip_ignored(tmp_path, value):
    path = write(tmp_path, "x " + value + ".4")
    assert "private-ip" not in kinds(scan([path], []))
