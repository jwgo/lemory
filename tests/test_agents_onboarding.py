"""Managed AGENTS.md guidance + git autocommit checkpoints (Tolaria absorb)."""

import subprocess

from lemory.interfaces.agents import (detect_agents, guidance_status,
                                      install_guidance)


def test_install_creates_managed_files(tmp_path):
    st = guidance_status(tmp_path)
    assert st == {"AGENTS.md": "missing", "CLAUDE.md": "missing", "GEMINI.md": "missing"}
    acts = install_guidance(tmp_path)
    assert all(a == "written" for a in acts.values())
    st = guidance_status(tmp_path)
    assert all(s == "managed" for s in st.values())
    text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "lemory search" in text and "save_memory" in text
    assert "lemory: false" in text  # privacy rule reaches every agent
    # second run is a no-op
    assert all(a == "current" for a in install_guidance(tmp_path).values())


def test_custom_files_are_sacred(tmp_path):
    (tmp_path / "AGENTS.md").write_text("# my own rules\nnever touch this",
                                        encoding="utf-8")
    st = guidance_status(tmp_path)
    assert st["AGENTS.md"] == "custom"
    acts = install_guidance(tmp_path, refresh=True)
    assert acts["AGENTS.md"] == "kept"
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8").startswith("# my own rules")
    # the shims were still created alongside
    assert acts["CLAUDE.md"] == "written"


def test_broken_empty_file_is_repaired(tmp_path):
    (tmp_path / "AGENTS.md").write_text("   \n", encoding="utf-8")
    assert guidance_status(tmp_path)["AGENTS.md"] == "broken"
    acts = install_guidance(tmp_path)
    assert acts["AGENTS.md"] == "written"
    assert guidance_status(tmp_path)["AGENTS.md"] == "managed"


def test_detect_agents_returns_hookups(tmp_path):
    agents = detect_agents(tmp_path)
    keys = {a.key for a in agents}
    assert {"claude-code", "codex", "cursor"} <= keys
    claude = next(a for a in agents if a.key == "claude-code")
    assert str(tmp_path) in claude.hookup and "claude mcp add lemory" in claude.hookup


def test_git_autocommit_records_ai_write(engine):
    from lemory.ingestion.memory import save_memory

    vault = engine.cfg.resolved_vault()
    subprocess.run(["git", "init", "-q"], cwd=vault, check=True)
    subprocess.run(["git", "-C", str(vault), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(vault), "config", "user.name", "t"], check=True)
    engine.cfg.git_autocommit = True
    engine.index()
    path = save_memory(engine, "결제 재시도는 지수 백오프 3회", title="재시도", client="test-agent")
    log = subprocess.run(["git", "-C", str(vault), "log", "--oneline", "-1"],
                         capture_output=True, text=True).stdout
    assert "lemory: memory by test-agent" in log
    assert str(path) in log


def test_git_autocommit_off_is_noop(engine):
    from lemory.ingestion.memory import save_memory

    vault = engine.cfg.resolved_vault()
    assert engine.cfg.git_autocommit is False
    engine.index()
    save_memory(engine, "커밋되면 안 되는 내용입니다", title="noop")
    assert not (vault / ".git").exists()  # never created a repo on its own
