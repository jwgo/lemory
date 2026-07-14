"""Coverage for the one-command onboarding (`lemory up` + deprecated init/setup
aliases) and the console Models-card backend (/api/assistant/model, the reranker
field in /api/config). These paths were previously only browser/manually
verified."""
from __future__ import annotations

import tomllib

import pytest
from typer.testing import CliRunner

from lemory.interfaces.cli import app


def _vault(tmp_path):
    v = tmp_path / "vault"
    v.mkdir()
    (v / "note.md").write_text("# 제목\n예산은 500만원.\n")
    return v


def test_up_writes_config_arg_form(tmp_path):
    v = _vault(tmp_path)
    r = CliRunner().invoke(app, ["up", str(v), "--no-index", "--no-serve"])
    assert r.exit_code == 0, r.output
    cfg = tomllib.loads((v / "lemory.toml").read_text())
    assert cfg["lemory"]["vault"] == str(v)
    assert cfg["lemory"].get("provider") == "local"  # keyless → local mode


def test_up_prompts_for_vault_when_bare(tmp_path):
    v = _vault(tmp_path)
    # bare `up` prompts for the vault; feed the path (and a declining 'n' in case
    # an environment without llama.cpp offers the Gemma install)
    r = CliRunner().invoke(app, ["up", "--no-index", "--no-serve"], input=f"{v}\nn\n")
    assert r.exit_code == 0, r.output
    assert (v / "lemory.toml").exists()


def test_up_rejects_missing_vault(tmp_path):
    r = CliRunner().invoke(app, ["up", str(tmp_path / "nope"), "--no-index", "--no-serve"])
    assert r.exit_code != 0


def test_up_key_selects_gemini(tmp_path):
    v = _vault(tmp_path)
    r = CliRunner().invoke(app, ["up", str(v), "--key", "test-key-123", "--no-index", "--no-serve"])
    assert r.exit_code == 0, r.output
    assert "Gemini" in r.output


@pytest.mark.parametrize("cmd", [["init"], ["setup", "--vault"]])
def test_deprecated_aliases_forward_and_notice(tmp_path, cmd):
    v = _vault(tmp_path)
    args = cmd + [str(v)] if cmd == ["init"] else cmd + [str(v), "--no-index-now"]
    r = CliRunner().invoke(app, args)
    assert r.exit_code == 0, r.output
    assert "lemory up" in r.output  # deprecation notice points at the new command
    assert (v / "lemory.toml").exists()


def test_init_setup_hidden_but_registered():
    import typer
    cmd = typer.main.get_command(app)
    subs = cmd.commands  # name -> click.Command
    assert "up" in subs and not subs["up"].hidden       # the one command is visible
    assert subs["init"].hidden and subs["setup"].hidden  # aliases kept but hidden


# ---- console Models-card backend ----

def _client(tmp_path):
    from fastapi.testclient import TestClient

    from lemory.config import LemoryConfig
    from lemory.engine import Engine
    from lemory.interfaces.http import build_app
    v = _vault(tmp_path)
    eng = Engine(LemoryConfig(vault=v, data_dir=tmp_path / "idx", provider="local"))
    # base_url satisfies the DNS-rebinding Host allowlist in build_app
    return TestClient(build_app(eng, watch=False), base_url="http://127.0.0.1")


def test_config_exposes_reranker_flag(tmp_path):
    r = _client(tmp_path).get("/api/config").json()
    assert "reranker" in r["readonly"]
    assert r["readonly"]["reranker"] is False  # ships off


def test_assistant_model_switch(tmp_path):
    c = _client(tmp_path)
    r = c.post("/api/assistant/model", json={"size": "E2B"})
    assert r.status_code == 200
    body = r.json()
    assert body["size"] == "E2B" and "E2B" in body["model"]
    # switch back
    assert c.post("/api/assistant/model", json={"size": "E4B"}).json()["size"] == "E4B"


def test_assistant_model_rejects_bad_size(tmp_path):
    r = _client(tmp_path).post("/api/assistant/model", json={"size": "BOGUS"})
    assert r.status_code == 400
