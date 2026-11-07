from wraith_tools import build_copilot

SRC = (
    "---\n"
    "name: tester\n"
    "description: Writes tests.\n"
    "model: sonnet\n"
    "tools: Read, Bash\n"
    "---\n"
    "# Body\r\n\n\nText  \n"
)


def make(root, stem="tester", text=SRC):
    agents = root / "agents"
    agents.mkdir(exist_ok=True)
    (agents / f"{stem}.md").write_bytes(text.encode())


def test_render_drops_model_and_keeps_order():
    out = build_copilot.render_agent(SRC, "tester")
    head = out.split("---\n")[1]
    assert head == (
        "name: tester\ndescription: Writes tests.\ntools: Read, Bash\n"
    )
    assert "model" not in out
    assert "<!-- GENERATED from agents/tester.md by" in out


def test_render_body_byte_identical():
    out = build_copilot.render_agent(SRC, "tester")
    body = SRC.split("---\n", 2)[2]
    assert out.endswith("-->\n\n" + body)


def test_check_reports_drift(tmp_path):
    make(tmp_path)
    assert build_copilot.build(tmp_path, True) == [
        "com.github.copilot/agents/tester.agent.md"
    ]
    build_copilot.build(tmp_path, False)
    target = tmp_path / "com.github.copilot/agents/tester.agent.md"
    target.write_text("edited")
    assert build_copilot.build(tmp_path, True) == [
        "com.github.copilot/agents/tester.agent.md"
    ]


def test_build_removes_orphans(tmp_path):
    make(tmp_path)
    build_copilot.build(tmp_path, False)
    orphan = tmp_path / "com.github.copilot/agents/gone.agent.md"
    orphan.write_text("x")
    rel = "com.github.copilot/agents/gone.agent.md"
    assert build_copilot.build(tmp_path, True) == [rel]
    assert orphan.exists()
    build_copilot.build(tmp_path, False)
    assert not orphan.exists()


def test_check_clean_after_build(tmp_path):
    make(tmp_path)
    build_copilot.build(tmp_path, False)
    assert build_copilot.build(tmp_path, True) == []


def test_main_modes(tmp_path, monkeypatch, capsys):
    make(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert build_copilot.main(["--check"]) == 1
    assert "tester.agent.md" in capsys.readouterr().out
    assert build_copilot.main([]) == 0
    assert "wrote 1 files" in capsys.readouterr().out
    assert build_copilot.main(["--check"]) == 0
    assert "copilot agents up to date" in capsys.readouterr().out
