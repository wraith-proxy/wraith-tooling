import json
import re
import subprocess
from pathlib import Path

import pytest
import yaml

from wraith_tools.vet_companion import (
    ADRS,
    addendum,
    bump_pin,
    bundle,
    fetch,
    main,
    parse_verdict,
    pins,
    pr_body,
    prompt,
    sanitize,
    title,
)

HERE = Path(__file__).resolve().parent
CZ = yaml.safe_load((HERE / "cz.yaml").read_text())["commitizen"]
SKILL = "skills/cloud/cloud-run-basics"
UNNAMED = "skills/cloud/gemini-api/SKILL.md"
OLD_SHA = "a" * 40
NEW_SHA = "b" * 40
PINS = f"""SP https://github.com/obra/superpowers v7.0.1 {"c" * 40}
GCP https://github.com/google/skills - {OLD_SHA}
TF https://github.com/hashicorp/agent-skills - {"d" * 40}
"""


def git(path, *args):
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com"]
        + ["-C", str(path), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def checkout(path, files):
    path.mkdir(parents=True)
    for name, text in files.items():
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        (path / name).write_text(text, encoding="utf-8")
    git(path, "init", "-q")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "x")
    return git(path, "rev-parse", "HEAD")


@pytest.fixture
def vetted(tmp_path):
    checkout(
        tmp_path / "old",
        {f"{SKILL}/SKILL.md": "a\n", f"{SKILL}/run.sh": "echo hi\n"},
    )
    checkout(
        tmp_path / "new",
        {
            f"{SKILL}/SKILL.md": "a\nask before deploys\n",
            f"{SKILL}/run.sh": (
                "echo hi\nterraform apply\n# see https://x.example\n"
            ),
            UNNAMED: "telemetry everywhere\n",
        },
    )
    out = tmp_path / "bundle"
    facts = bundle("GCP", tmp_path / "old", tmp_path / "new", out)
    return facts, out


def good_verdict(**extra):
    verdict = {
        "verdict": "changed",
        "summary": ["The skill now applies Terraform."],
        "risks": ["terraform apply"],
        "conflicts": ["Automate the guardrails, not the work"],
    }
    verdict.update(extra)
    return verdict


def claude_output(verdict):
    return json.dumps({"type": "result", "result": json.dumps(verdict)})


def test_bundle_holds_only_named_skill_changes(vetted):
    facts, out = vetted
    assert facts["key"] == "GCP"
    assert facts["skills"] == ["cloud-run-basics"]
    assert [f["path"] for f in facts["files"]] == [
        f"{SKILL}/SKILL.md",
        f"{SKILL}/run.sh",
    ]
    assert re.fullmatch(r"[0-9a-f]{64}", facts["fingerprint"])
    assert facts["truncated"] is False
    diff = (out / "diff.patch").read_text(encoding="utf-8")
    assert "+ask before deploys" in diff
    assert "telemetry" not in diff
    assert json.loads((out / "facts.json").read_text()) == facts


def test_bundle_records_risk_hits(vetted):
    facts, _ = vetted
    run_sh = facts["files"][1]
    assert any(h.startswith("terraform-apply:") for h in run_sh["hits"])
    assert any(h.startswith("new-url:") for h in run_sh["hits"])


def test_prompt_fences_the_diff_as_untrusted(vetted):
    facts, out = vetted
    text = prompt(out)
    nonce = facts["fingerprint"][:16]
    assert f"BEGIN UNTRUSTED DIFF {nonce}" in text
    assert f"END UNTRUSTED DIFF {nonce}" in text
    assert text.index("BEGIN UNTRUSTED") < text.index("+ask before deploys")
    assert "never follow" in text.lower()
    assert '"verdict"' in text


def test_valid_verdict_passes_through(vetted):
    facts, _ = vetted
    found = parse_verdict(claude_output(good_verdict()), facts)
    assert found["verdict"] == "changed"
    assert found["summary"] == good_verdict()["summary"]


def test_verdict_found_inside_prose(vetted):
    facts, _ = vetted
    text = "Here it is:\n" + json.dumps(good_verdict()) + "\nDone."
    raw = json.dumps({"result": text})
    assert parse_verdict(raw, facts)["verdict"] == "changed"


def test_structured_output_is_used_when_present(vetted):
    facts, _ = vetted
    raw = json.dumps({"result": "", "structured_output": good_verdict()})
    assert parse_verdict(raw, facts)["verdict"] == "changed"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "{}",
        "not json at all",
        json.dumps({"result": "no object here"}),
        json.dumps({"is_error": True, "result": json.dumps(good_verdict())}),
        claude_output(good_verdict(verdict="approve")),
        claude_output(good_verdict(summary="not a list")),
        claude_output(good_verdict(summary=[])),
        claude_output(good_verdict(risks=[1, 2])),
    ],
)
def test_anything_else_falls_back_to_unread(vetted, raw):
    facts, _ = vetted
    found = parse_verdict(raw, facts)
    assert found["verdict"] == "unread"
    assert found["note"]


def test_truncated_bundle_is_never_machine_accepted(vetted):
    facts, _ = vetted
    facts = {**facts, "truncated": True}
    raw = claude_output(good_verdict(verdict="unchanged"))
    assert parse_verdict(raw, facts)["verdict"] == "unread"


def test_long_lists_and_strings_are_capped(vetted):
    facts, _ = vetted
    verdict = good_verdict(summary=["x" * 900] * 20, risks=["r"] * 30)
    found = parse_verdict(claude_output(verdict), facts)
    assert len(found["summary"]) == 6
    assert len(found["risks"]) == 10
    assert all(len(s) <= 300 for s in found["summary"])


def test_sanitize_strips_mentions_html_fences_and_secrets():
    text = sanitize(
        "ping @someone <!-- hide --> ```x``` key sk-ant-api03-abcDEF_123 "
        "ghs_" + "A" * 36 + " done\u2014ok\nnext"
    )
    assert "@" not in text
    assert "<" not in text and ">" not in text
    assert "```" not in text
    assert "sk-ant" not in text and "ghs_" not in text
    assert "[redacted]" in text
    assert "\u2014" not in text and "\n" not in text


def test_addendum_records_the_facts_and_the_read(vetted):
    facts, _ = vetted
    verdict = parse_verdict(claude_output(good_verdict()), facts)
    text = addendum(facts, verdict, 95, "2026-11-05")
    assert text.startswith("## Addendum 2026-11-05: pin bumped to ")
    assert "Ticket: WSK-00095." in text
    assert facts["new_sha"] in text
    assert "`cloud-run-basics`" in text
    assert "terraform-apply" in text
    assert "Machine read, verdict changed" in text
    assert "The owner accepts the bump by merging it" in text
    assert "\u2014" not in text


def test_unread_addendum_says_a_human_must_read(vetted):
    facts, _ = vetted
    verdict = parse_verdict("", facts)
    text = addendum(facts, verdict, 95, "2026-11-05")
    assert "No machine read" in text
    assert "a human must read the diff" in text


def test_pins_and_bump_change_only_the_named_key():
    assert pins(PINS)["GCP"] == (
        "https://github.com/google/skills",
        "-",
        OLD_SHA,
    )
    bumped = bump_pin(PINS, "GCP", NEW_SHA)
    assert f"GCP https://github.com/google/skills - {NEW_SHA}" in bumped
    assert bumped.replace(NEW_SHA, OLD_SHA) == PINS
    with pytest.raises(KeyError):
        bump_pin(PINS, "DBT", NEW_SHA)


def test_title_is_a_valid_non_releasing_subject(vetted):
    facts, _ = vetted
    subject = title(facts, 95)
    assert (
        subject
        == f"\U0001f47b chore/WSK-00095: re-vet GCP and pin {facts['new_sha'][:7]}"
    )
    assert re.match(CZ["customize"]["schema_pattern"], subject)
    assert not re.match(CZ["customize"]["bump_pattern"], subject)


def test_pr_body_closes_the_issue_and_carries_the_diff(vetted):
    facts, out = vetted
    verdict = parse_verdict(claude_output(good_verdict()), facts)
    diff = (out / "diff.patch").read_text(encoding="utf-8")
    body = pr_body(facts, verdict, 95, diff)
    assert body.startswith("Closes #95.")
    assert "Not merged automatically" in body
    assert "+ask before deploys" in body
    assert "<details>" in body
    assert "had no tools" in body


def test_pr_body_truncates_a_huge_diff(vetted):
    facts, _ = vetted
    verdict = parse_verdict("", facts)
    body = pr_body(facts, verdict, 95, "+x\n" * 40000)
    assert len(body) < 60000
    assert "diff truncated" in body


def test_cli_end_to_end_writes_pin_adr_and_pr_body(vetted, tmp_path, capsys):
    facts, out = vetted
    (out / "raw.json").write_text(
        claude_output(good_verdict()), encoding="utf-8"
    )
    assert (
        main(["verdict", "--bundle", str(out), "--raw", str(out / "raw.json")])
        == 0
    )
    root = tmp_path / "repo"
    (root / "docs" / "adr").mkdir(parents=True)
    fetch_sh = PINS.replace(OLD_SHA, facts["old_sha"])
    (root / "upstream-pins.txt").write_text(fetch_sh, encoding="utf-8")
    (root / "docs" / "adr" / ADRS["GCP"]).write_text(
        "# ADR\n", encoding="utf-8"
    )
    capsys.readouterr()
    args = [
        "apply",
        "--bundle",
        str(out),
        "--ticket",
        "95",
        "--root",
        str(root),
    ]
    assert (
        main(
            [
                *args,
                "--pr-body",
                str(tmp_path / "body.md"),
                "--date",
                "2026-11-05",
            ]
        )
        == 0
    )
    assert capsys.readouterr().out.strip() == title(facts, 95)
    pinned = (root / "upstream-pins.txt").read_text(encoding="utf-8")
    assert facts["new_sha"] in pinned and facts["old_sha"] not in pinned
    adr = (root / "docs" / "adr" / ADRS["GCP"]).read_text(encoding="utf-8")
    assert adr.startswith("# ADR\n\n## Addendum 2026-11-05")
    assert (
        (tmp_path / "body.md")
        .read_text(encoding="utf-8")
        .startswith("Closes #95.")
    )


def test_apply_without_drift_prints_nothing(tmp_path, capsys):
    checkout(tmp_path / "old", {f"{SKILL}/SKILL.md": "a\n"})
    checkout(tmp_path / "new", {f"{SKILL}/SKILL.md": "a\n", UNNAMED: "b\n"})
    out = tmp_path / "bundle"
    bundle("GCP", tmp_path / "old", tmp_path / "new", out)
    assert (
        main(
            ["verdict", "--bundle", str(out), "--raw", str(tmp_path / "none")]
        )
        == 0
    )
    args = [
        "apply",
        "--bundle",
        str(out),
        "--ticket",
        "95",
        "--root",
        str(tmp_path),
    ]
    capsys.readouterr()
    assert main([*args, "--pr-body", str(tmp_path / "body.md")]) == 0
    assert capsys.readouterr().out == ""


def test_fetch_checks_out_the_exact_sha(tmp_path):
    first = checkout(tmp_path / "up", {"f.md": "one\n"})
    (tmp_path / "up" / "f.md").write_text("two\n", encoding="utf-8")
    git(tmp_path / "up", "commit", "-qam", "two")
    fetch(f"file://{tmp_path / 'up'}", first, tmp_path / "got")
    assert git(tmp_path / "got", "rev-parse", "HEAD") == first
    assert (tmp_path / "got" / "f.md").read_text(encoding="utf-8") == "one\n"


def test_fetch_cli_defaults_to_the_pinned_sha(tmp_path, monkeypatch):
    sha = checkout(tmp_path / "up", {"f.md": "one\n"})
    pins_file = tmp_path / "upstream-pins.txt"
    pins_file.write_text(
        PINS.replace(
            "https://github.com/google/skills", f"file://{tmp_path / 'up'}"
        ).replace(OLD_SHA, sha),
        encoding="utf-8",
    )
    args = ["fetch", "--key", "GCP", "--dest", str(tmp_path / "got")]
    assert main([*args, "--pins", str(pins_file)]) == 0
    assert git(tmp_path / "got", "rev-parse", "HEAD") == sha
