import json

from wraith_tools.drift_issues import decide, fingerprint, main, sections

FP = "a" * 64
REPORT = f"""# Upstream sync

| KEY | Old ref | New ref | New SHA |

## Companion drift

### GCP

<!-- drift-fingerprint: GCP {FP} -->
- skills/cloud/cloud-run-basics/SKILL.md

### TF

<!-- drift-fingerprint: TF {"b" * 64} -->
- plugins/terraform/skills/terraform-test/SKILL.md
"""


def issue(number, state, body="", title="re-vet GCP"):
    return {"number": number, "title": title, "state": state, "body": body}


def test_sections_split_the_drift_report_by_key():
    found = sections(REPORT)
    assert list(found) == ["GCP", "TF"]
    assert found["GCP"].startswith("### GCP\n")
    assert "cloud-run-basics" in found["GCP"]
    assert "terraform-test" not in found["GCP"]


def test_sections_are_empty_without_drift():
    assert sections("# Upstream sync\n\nnothing\n") == {}


def test_fingerprint_reads_the_marker():
    assert fingerprint(sections(REPORT)["GCP"]) == f"GCP {FP}"
    assert fingerprint("### GCP\n- x\n") is None


def test_open_issue_is_edited():
    body = sections(REPORT)["GCP"]
    issues = [issue(7, "CLOSED", body), issue(9, "OPEN")]
    assert decide("GCP", body, issues) == ("edit", 9)


def test_open_issue_with_the_same_fingerprint_is_kept():
    body = sections(REPORT)["GCP"]
    assert decide("GCP", body, [issue(9, "OPEN", body)]) == ("keep", 9)


def test_open_legacy_issue_without_fingerprint_is_edited():
    body = sections(REPORT)["GCP"]
    legacy = issue(80, "OPEN", "### GCP\n\nNo SKILL.md changes.\n")
    assert decide("GCP", body, [legacy]) == ("edit", 80)


def test_closed_issue_with_the_same_fingerprint_is_not_reopened():
    body = sections(REPORT)["GCP"]
    assert decide("GCP", body, [issue(7, "CLOSED", body)]) == ("skip", 7)


def test_new_changes_after_a_closed_issue_open_a_new_one():
    body = sections(REPORT)["GCP"]
    old = body.replace(FP, "c" * 64)
    assert decide("GCP", body, [issue(7, "CLOSED", old)]) == ("create", None)


def test_legacy_closed_issue_without_fingerprint_does_not_block():
    body = sections(REPORT)["GCP"]
    legacy = issue(80, "CLOSED", "### GCP\n\n- skills/cloud/gemini-api\n")
    assert decide("GCP", body, [legacy]) == ("create", None)


def test_body_without_fingerprint_never_skips():
    body = "### GCP\n- x\n"
    assert decide("GCP", body, [issue(7, "CLOSED", body)]) == ("create", None)


def test_other_keys_issues_are_ignored():
    body = sections(REPORT)["GCP"]
    other = issue(5, "OPEN", body, title="re-vet TF")
    assert decide("GCP", body, [other]) == ("create", None)


def test_main_writes_bodies_and_prints_actions(tmp_path, capsys):
    report = tmp_path / "sync-report.md"
    report.write_text(REPORT, encoding="utf-8")
    gcp = sections(REPORT)["GCP"]
    issues = tmp_path / "issues.json"
    issues.write_text(json.dumps([issue(7, "CLOSED", gcp)]), encoding="utf-8")
    argv = ["--report", str(report), "--issues", str(issues)]
    assert main([*argv, "--out", str(tmp_path)]) == 0
    assert capsys.readouterr().out.splitlines() == ["skip GCP 7", "create TF"]
    assert (tmp_path / "body-GCP.md").read_text(encoding="utf-8") == gcp
    assert (tmp_path / "body-TF.md").exists()
