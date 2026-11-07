import subprocess
import sys

import pytest

from wraith_tools.release_notes import build_notes

HEADING = "What changes for you"
HEADER_COMMENT = (
    "<!--\nEdit this file in a feature or break PR. Its body becomes\n"
    "the user-facing paragraph of the release notes.\n-->\n"
)
USER = "You can now install the plugin with one command."

FEATURE = "## v0.6.0 (2026-11-04)\n\n### Features\n\n- add thing (#40)\n"
BREAK = (
    "## v0.7.0 (2026-11-04)\n\n### Breaking Changes\n\n- rename skill (#41)\n"
)
PATCH = "## v0.5.10 (2026-11-04)\n\n### Bug Fixes\n\n- fix thing (#42)\n"


@pytest.mark.parametrize(
    "generated, item",
    [(FEATURE, "- add thing (#40)"), (BREAK, "- rename skill (#41)")],
)
def test_user_paragraph_goes_above_generated_list(generated, item):
    out = build_notes(generated, USER)
    assert HEADING in out
    assert USER in out
    assert out.index(HEADING) < out.index(USER) < out.index(item)
    assert out.startswith(HEADING) or out.lstrip("# ").startswith(HEADING)


def test_patch_release_keeps_generated_notes_unchanged():
    assert build_notes(PATCH, USER) == PATCH


def test_feature_release_without_user_notes_is_unchanged():
    assert build_notes(FEATURE, None) == FEATURE


@pytest.mark.parametrize(
    "user", [HEADER_COMMENT, "  \n\n", HEADER_COMMENT + "\n  \n"]
)
def test_comment_only_or_blank_user_notes_count_as_empty(user):
    assert build_notes(FEATURE, user) == FEATURE


def test_cli_prints_paragraph_above_generated(tmp_path):
    gen = tmp_path / "gen.md"
    usr = tmp_path / "user.md"
    gen.write_text(FEATURE)
    usr.write_text(HEADER_COMMENT + USER + "\n")
    res = subprocess.run(
        [
            sys.executable,
            "-m",
            "wraith_tools.release_notes",
            "--generated",
            str(gen),
            "--user",
            str(usr),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert res.stdout.index(USER) < res.stdout.index("- add thing (#40)")


def test_cli_without_user_prints_generated(tmp_path):
    gen = tmp_path / "gen.md"
    gen.write_text(FEATURE)
    res = subprocess.run(
        [
            sys.executable,
            "-m",
            "wraith_tools.release_notes",
            "--generated",
            str(gen),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert res.stdout.strip() == FEATURE.strip()
