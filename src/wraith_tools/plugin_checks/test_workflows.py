import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path.cwd() / ".github" / "workflows"
AUTO_MERGE = "Enable auto-merge on safe syncs"
STUB_GH = """#!/bin/bash
echo "gh $*" >> "$STUB_LOG"
case "$1 $2" in
  "api repos/"*)
    [ "$RULES" = fail ] && exit 1
    echo "$RULES";;
  "pr view") echo "x";;
  "api graphql") [ "$GQL" = ok ] || exit 1;;
esac
exit 0
"""


def text(name):
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def sync_steps():
    return yaml.safe_load(text("upstream-sync.yml"))["jobs"]["sync"]["steps"]


def sync_step(name):
    return next(s for s in sync_steps() if s.get("name") == name)


def test_ci_has_only_the_test_job():
    assert list(yaml.safe_load(text("ci.yml"))["jobs"]) == ["test"]


def test_ci_reruns_when_a_pr_title_is_edited():
    # PyYAML reads the workflow's `on:` key as the boolean True.
    on = yaml.safe_load(text("ci.yml"))[True]
    assert "edited" in on["pull_request"]["types"]


def test_test_job_checks_the_pr_title_before_anything_slow():
    steps = yaml.safe_load(text("ci.yml"))["jobs"]["test"]["steps"]
    runs = [s.get("run", "") for s in steps]
    check = 'uvx --from commitizen==4.19.3 cz check --message "$TITLE"'
    title = steps[runs.index(check)]
    assert title["if"] == "github.event_name == 'pull_request'"
    assert title["env"]["TITLE"] == "${{ github.event.pull_request.title }}"
    pre_commit = (
        "uvx --python 3.12 pre-commit run --all-files --show-diff-on-failure"
    )
    tooling = next(
        i
        for i, s in enumerate(steps)
        if s.get("uses", "").startswith("wraith-proxy/wraith-tooling@")
    )
    assert steps.index(title) < tooling
    assert steps.index(title) < runs.index(pre_commit)


@pytest.mark.parametrize("name", ["ci.yml", "upstream-sync.yml"])
def test_no_automerge_title_tag(name):
    assert "[automerge]" not in text(name)


def test_sync_auto_merges_only_safe_syncs():
    condition = sync_step(AUTO_MERGE)["if"]
    assert "steps.sync.outputs.code == '10'" in condition
    assert "steps.evals.outputs.ok != 'false'" in condition


def test_sync_auto_merge_uses_the_app_token():
    token = sync_step(AUTO_MERGE)["env"]["GH_TOKEN"]
    assert token == "${{ steps.app.outputs.token }}"


def test_sync_auto_merge_runs_after_the_risk_flag():
    names = [s.get("name") for s in sync_steps()]
    assert names.index("Flag risky syncs") < names.index(AUTO_MERGE)


def test_sync_auto_merge_squashes_with_the_pr_title():
    run = sync_step(AUTO_MERGE)["run"]
    assert "mergeMethod: SQUASH" in run
    assert "commitHeadline: $headline" in run


@pytest.mark.parametrize(
    ("rules", "graphql", "enabled"),
    [
        ("1", "ok", True),
        ("0", "ok", False),
        ("fail", "ok", False),
        ("1", "refused", False),
    ],
)
def test_auto_merge_needs_a_required_check_or_waits_for_review(
    tmp_path, rules, graphql, enabled
):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(STUB_GH)
    gh.chmod(0o755)
    log = tmp_path / "gh.log"
    log.touch()
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "RULES": rules,
        "GQL": graphql,
        "STUB_LOG": str(log),
        "PR_URL": "https://example.com/pr/1",
        "GITHUB_REPOSITORY": "owner/repo",
    }
    result = subprocess.run(
        ["bash", "-e", "-c", sync_step(AUTO_MERGE)["run"]],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert ("auto-merge enabled" in result.stdout) is enabled
    assert ("--add-label needs-review" in log.read_text()) is not enabled


def app_token_steps():
    for path in sorted(WORKFLOWS.glob("*.yml")):
        jobs = yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"]
        for job in jobs.values():
            for step in job.get("steps", []):
                uses = step.get("uses", "")
                if uses.startswith("actions/create-github-app-token@"):
                    yield path.name, step


def test_app_token_steps_use_client_id_not_deprecated_app_id():
    found = list(app_token_steps())
    # release, the sync job and the propose job (#95) each mint a token.
    assert sorted(name for name, _ in found) == [
        "release.yml",
        "upstream-sync.yml",
        "upstream-sync.yml",
    ]
    for _, step in found:
        assert "app-id" not in step["with"]
        assert step["with"]["client-id"] == "${{ secrets.WRAITH_BOT_APP_ID }}"


def test_drift_issues_come_from_the_tested_helper():
    step = sync_step("Companion drift issues")
    run = step["run"]
    assert step["env"]["GH_TOKEN"] == "${{ steps.app.outputs.token }}"
    assert "gh issue list --state all" in run
    assert "wraith-drift-issues" in run
    assert "--search" not in run


def job(name):
    return yaml.safe_load(text("upstream-sync.yml"))["jobs"][name]


def job_text(name):
    return yaml.safe_dump(job(name))


def test_sync_exports_the_vet_queue():
    assert job("sync")["outputs"]["vet"] == "${{ steps.drift.outputs.vet }}"
    assert sync_step("Companion drift issues")["id"] == "drift"


def test_vet_job_holds_no_write_credentials():
    vet = job("vet")
    assert vet["permissions"] == {"contents": "read"}
    uses = [s.get("uses", "") for s in vet["steps"]]
    assert not any("create-github-app-token" in u for u in uses)
    checkout = vet["steps"][0]
    assert checkout["uses"].startswith("actions/checkout@")
    assert checkout["with"]["persist-credentials"] is False
    assert "GH_TOKEN" not in job_text("vet")
    with_key = [s for s in vet["steps"] if "ANTHROPIC_API_KEY" in str(s)]
    assert [s["name"] for s in with_key] == ["Machine read"]


def test_machine_read_has_no_tools_and_a_budget():
    step = next(
        s for s in job("vet")["steps"] if s.get("name") == "Machine read"
    )
    run = step["run"]
    for flag in ("--bare", '--tools ""', "--no-session-persistence"):
        assert flag in run
    assert "--max-budget-usd 1" in run
    for loose in ("--allowedTools", "bypassPermissions", "--dangerously"):
        assert loose not in run


def test_propose_job_opens_a_review_pr_and_never_merges():
    propose = job("propose")
    assert propose["needs"] == ["sync", "vet"]
    assert propose["permissions"] == {"contents": "read"}
    body = job_text("propose")
    assert "--label needs-review" in body
    assert "gh pr create" in body
    for merge in ("gh pr merge", "enablePullRequestAutoMerge", "--auto"):
        assert merge not in body


STUB_UV = """#!/bin/bash
printf '%s\\n' "create GCP" "edit TF 81" "keep DBT 5" "skip SP 7"
"""
STUB_ISSUES = """#!/bin/bash
echo "gh $*" >> "$STUB_LOG"
case "$1 $2" in
  "issue list") echo "[]";;
  "issue create") echo "https://github.com/o/r/issues/101";;
esac
exit 0
"""


def test_drift_step_queues_new_and_changed_drift_only(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, script in (
        ("wraith-drift-issues", STUB_UV),
        ("gh", STUB_ISSUES),
    ):
        (bin_dir / name).write_text(script)
        (bin_dir / name).chmod(0o755)
    shas = {}
    for key in ("GCP", "TF", "DBT", "SP"):
        repo = tmp_path / ".upstream-new" / key
        repo.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "-c", "user.name=t"]
            + ["-c", "user.email=t@example.com"]
            + ["commit", "-q", "--allow-empty", "-m", key],
            check=True,
        )
        shas[key] = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    output = tmp_path / "github_output"
    log = tmp_path / "gh.log"
    log.touch()
    env = {
        **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "GITHUB_OUTPUT": str(output),
        "STUB_LOG": str(log),
        "GH_TOKEN": "x",
    }
    result = subprocess.run(
        ["bash", "-e", "-c", sync_step("Companion drift issues")["run"]],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    line = output.read_text().strip()
    assert line.startswith("vet=")
    assert json.loads(line[4:]) == [
        {"key": "GCP", "issue": 101, "sha": shas["GCP"]},
        {"key": "TF", "issue": 81, "sha": shas["TF"]},
    ]
    calls = log.read_text()
    assert "issue create --title re-vet GCP" in calls
    assert "issue edit 81" in calls
    assert "DBT" not in calls and "SP" not in calls
