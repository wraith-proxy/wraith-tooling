import os

from wraith_tools import lint_skills

NOTICES = "# Third-party notices\n\n## SP\n\nx\n\n## MP\n\nx\n"
EM = chr(0x2014)


def skill(name="demo", **over):
    fm = {
        "name": name,
        "description": "Use when testing.",
        "license": "MIT",
        "metadata": "\n  source: new",
    }
    fm.update(over)
    lines = [f"{k}: {v}" for k, v in fm.items() if v is not None]
    return "---\n" + "\n".join(lines) + "\n---\n\nBody.\n"


AGENT = (
    "---\nname: bot\ndescription: Does things.\nmodel: sonnet\n"
    "tools: Read, Grep\n---\n\nBody.\n\n## When you finish, report\n\nok\n"
)


def make_repo(tmp_path, files):
    files = {"THIRD_PARTY_NOTICES.md": NOTICES, **files}
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


def rules(problems):
    return {p.split(": ", 1)[1].split()[0] for p in problems}


def test_clean_repo_passes(tmp_path, capsys):
    make_repo(
        tmp_path,
        {
            "skills/demo/SKILL.md": skill(),
            "skills/demo/ref.md": "see [s](SKILL.md)\n",
            "agents/bot.md": AGENT,
            "README.md": "hi wraith:demo wraith:bot\n",
        },
    )
    assert lint_skills.lint(tmp_path) == []
    assert lint_skills.main([str(tmp_path)]) == 0
    assert "0 problems" in capsys.readouterr().out


def test_empty_repo_passes(tmp_path):
    assert lint_skills.lint(tmp_path) == []


def test_main_reports_problems(tmp_path, capsys):
    make_repo(tmp_path, {"skills/demo/other.md": "x"})
    assert lint_skills.main([str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "skills/demo: L1" in out
    assert "1 problems" in out


def test_main_defaults_to_cwd(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert lint_skills.main([]) == 0


def test_frontmatter_missing_or_not_mapping(tmp_path):
    make_repo(
        tmp_path,
        {
            "skills/a/SKILL.md": "no frontmatter\n",
            "skills/b/SKILL.md": "---\n- x\n---\n",
            "skills/c/SKILL.md": "---\nname: [\n---\n",
            "skills/d/SKILL.md": "---\nname: d\n",
        },
    )
    probs = lint_skills.lint(tmp_path)
    assert len([p for p in probs if " L2 " in p]) == 4


def test_lint_rejects_non_portable_keys(tmp_path):
    make_repo(
        tmp_path,
        {
            "skills/demo/SKILL.md": skill(
                **{"disable-model-invocation": "true"}
            )
        },
    )
    assert "L3" in rules(lint_skills.lint(tmp_path))


def test_name_must_match_directory(tmp_path):
    make_repo(
        tmp_path,
        {
            "skills/demo/SKILL.md": skill(name="other"),
            "skills/Bad_Name/SKILL.md": skill(name="Bad_Name"),
            "skills/num/SKILL.md": skill(name="123"),
            "skills/nameless/SKILL.md": skill(name=None),
        },
    )
    probs = [p for p in lint_skills.lint(tmp_path) if " L4 " in p]
    assert len(probs) >= 3
    assert any(p.startswith("skills/demo/SKILL.md") for p in probs)
    assert any(p.startswith("skills/nameless/SKILL.md") for p in probs)


def test_name_too_long(tmp_path):
    n = "a" * 65
    make_repo(tmp_path, {f"skills/{n}/SKILL.md": skill(name=n)})
    assert "L4" in rules(lint_skills.lint(tmp_path))


def test_description_over_400_characters(tmp_path):
    make_repo(
        tmp_path,
        {
            "skills/demo/SKILL.md": skill(description="x" * 401),
            "skills/e/SKILL.md": skill(name="e", description=None),
        },
    )
    probs = [p for p in lint_skills.lint(tmp_path) if " L5 " in p]
    assert len(probs) == 2


def test_compat_and_metadata_types(tmp_path):
    make_repo(
        tmp_path,
        {
            "skills/demo/SKILL.md": skill(compatibility="x" * 501),
            "skills/b/SKILL.md": skill(
                name="b", metadata="\n  source: new\n  n: 3"
            ),
            "skills/c/SKILL.md": skill(name="c", metadata="[a]"),
        },
    )
    probs = [p for p in lint_skills.lint(tmp_path) if " L6 " in p]
    assert len(probs) == 3


def test_skill_md_line_cap(tmp_path):
    big = skill() + "line\n" * 400
    wide = skill() + "x" * 20001
    make_repo(
        tmp_path,
        {"skills/demo/SKILL.md": big, "skills/wide/SKILL.md": wide},
    )
    probs = [p for p in lint_skills.lint(tmp_path) if " L8 " in p]
    assert len(probs) == 2


def test_broken_reference_link(tmp_path):
    make_repo(
        tmp_path,
        {
            "skills/demo/SKILL.md": skill()
            + "[a](nope.md) [b](../x/SKILL.md) [c](https://e.com) "
            "[d](#top) [e](ref.md#sec)\n",
            "skills/demo/ref.md": "x",
            "skills/x/SKILL.md": skill(name="x"),
        },
    )
    probs = [p for p in lint_skills.lint(tmp_path) if " L9 " in p]
    assert len(probs) == 2


def test_unresolved_wraith_reference(tmp_path):
    make_repo(
        tmp_path,
        {
            "skills/demo/SKILL.md": skill() + "use wraith:ghost\n",
            "hooks/h.py": "# wraith:phantom\n",
            "agents/bot.md": AGENT + "wraith:demo wraith:bot\n",
        },
    )
    probs = [p for p in lint_skills.lint(tmp_path) if " L10 " in p]
    assert len(probs) == 2


def test_em_dash_rejected(tmp_path):
    make_repo(
        tmp_path,
        {
            "skills/demo/SKILL.md": skill() + f"a {EM} b\n",
            "README.md": f"a{EM}b\n",
            "docs/x.md": f"a{EM}b\n",
        },
    )
    probs = [p for p in lint_skills.lint(tmp_path) if " L11 " in p]
    assert len(probs) == 2


def test_agent_model_must_be_alias(tmp_path):
    make_repo(
        tmp_path,
        {
            "agents/bot.md": AGENT.replace("sonnet", "gpt"),
            "agents/other.md": AGENT,
            "agents/nofm.md": "plain\n",
        },
    )
    probs = lint_skills.lint(tmp_path)
    assert any("agents/bot.md: L12" in p and "model" in p for p in probs)
    assert any("agents/other.md: L12" in p and "name" in p for p in probs)
    assert any("agents/nofm.md: L2" in p for p in probs)


def test_agent_keys_description_and_length(tmp_path):
    text = AGENT.replace("tools:", "color: red\ntools:").replace(
        "Does things.", "d" * 401
    )
    text += "line\n" * 120
    make_repo(tmp_path, {"agents/bot.md": text})
    probs = [p for p in lint_skills.lint(tmp_path) if " L12 " in p]
    assert len(probs) == 3


def test_agent_needs_report_section(tmp_path):
    make_repo(
        tmp_path,
        {"agents/bot.md": AGENT.replace("## When you finish, report", "x")},
    )
    assert "L12" in rules(lint_skills.lint(tmp_path))


def test_upstream_tokens_rejected(tmp_path):
    fm = skill(description="superpowers: in frontmatter is ignored")
    make_repo(
        tmp_path,
        {
            "skills/demo/SKILL.md": fm + "see superpowers:foo\n",
            "skills/demo/ref.md": "uses .gstack dir\n",
            "agents/bot.md": AGENT + "office-hours\n",
            "hooks/h.py": "# gstack-x\n",
            "agents/ok.md": AGENT.replace("bot", "ok")
            + "<!-- source: SP@abcdef1:x office-hours -->\n",
            "skills/fm/SKILL.md": skill(
                name="fm", description="'superpowers:'"
            ),
        },
    )
    probs = [p for p in lint_skills.lint(tmp_path) if " L13 " in p]
    assert len(probs) == 4


def test_bin_directory_and_symlink_rejected(tmp_path):
    make_repo(tmp_path, {"bin/tool": "x", "real.txt": "x"})
    os.symlink(tmp_path / "real.txt", tmp_path / "link.txt")
    probs = lint_skills.lint(tmp_path)
    assert rules(probs) == {"L15"}
    assert len(probs) == 2


def test_size_and_count_limits(tmp_path, monkeypatch):
    make_repo(tmp_path, {"big.bin": "x" * (256 * 1024 + 1)})
    assert "L14" in rules(lint_skills.lint(tmp_path))
    monkeypatch.setattr(lint_skills, "MAX_FILES", 2)
    (tmp_path / "evals/results").mkdir(parents=True)
    (tmp_path / "evals/results/skip.txt").write_text("x")
    (tmp_path / "b.txt").write_text("x")
    probs = [p for p in lint_skills.lint(tmp_path) if "files" in p]
    assert len(probs) == 1


def test_too_many_skills(tmp_path):
    files = {f"skills/s{i}/SKILL.md": skill(name=f"s{i}") for i in range(31)}
    make_repo(tmp_path, files)
    assert "L16" in rules(lint_skills.lint(tmp_path))


def test_missing_skill_md(tmp_path):
    make_repo(tmp_path, {"skills/demo/x.md": "x"})
    assert "L1" in rules(lint_skills.lint(tmp_path))


def test_metadata_source_format_and_notice_key(tmp_path):
    ok = "\n  source: SP@abcdef1:a/b.md, MP@1234567:c"
    make_repo(
        tmp_path,
        {
            "skills/demo/SKILL.md": skill(metadata=ok),
            "skills/bad/SKILL.md": skill(
                name="bad", metadata="\n  source: SP@xyz:a"
            ),
            "skills/key/SKILL.md": skill(
                name="key", metadata="\n  source: KA@abcdef1:a"
            ),
            "skills/lic/SKILL.md": skill(name="lic", license="GPL"),
            "skills/nosrc/SKILL.md": skill(name="nosrc", metadata="{}"),
            "skills/nolic/SKILL.md": skill(name="nolic", license=None),
        },
    )
    probs = [p for p in lint_skills.lint(tmp_path) if " L7 " in p]
    assert not any("skills/demo" in p for p in probs)
    assert len(probs) == 5


def test_missing_notices_file(tmp_path):
    (tmp_path / "skills/demo").mkdir(parents=True)
    (tmp_path / "skills/demo/SKILL.md").write_text(
        skill(metadata="\n  source: SP@abcdef1:a")
    )
    assert "L7" in rules(lint_skills.lint(tmp_path))


def test_subfolder_plugin_and_root_em_dash(tmp_path):
    make_repo(
        tmp_path,
        {
            ".claude-plugin/marketplace.json": (
                '{"plugins":[{"source":"./plugin"}]}'
            ),
            "plugin/THIRD_PARTY_NOTICES.md": NOTICES,
            "plugin/skills/demo/SKILL.md": skill(),
            "evals/x.md": f"a {EM} b\n",
        },
    )
    problems = lint_skills.lint(tmp_path)
    assert [p for p in problems if p.startswith("evals/x.md: L11")]


def test_subfolder_problems_are_reported_from_the_repo_root(tmp_path):
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin" / "marketplace.json").write_text(
        '{"plugins": [{"source": "./plugin"}]}'
    )
    (tmp_path / "plugin" / "skills" / "broken").mkdir(parents=True)
    problems = lint_skills.lint(tmp_path)
    assert problems
    assert all(p.startswith("plugin/") for p in problems), problems
