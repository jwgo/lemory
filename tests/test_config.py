import os

import pytest

from lemory.config import LemoryConfig, load_config


def test_defaults_are_sane():
    cfg = LemoryConfig()
    assert cfg.llm_model.startswith("gemini")
    assert cfg.embed_dim == 768
    assert cfg.chunk_chars > cfg.chunk_overlap


def test_resolved_vault_requires_vault():
    with pytest.raises(RuntimeError, match="No vault configured"):
        LemoryConfig().resolved_vault()


def test_resolved_api_key_error(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="No Gemini API key"):
        LemoryConfig().resolved_api_key()


def test_api_key_from_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k1")
    assert LemoryConfig().resolved_api_key() == "k1"


def test_data_dir_defaults_inside_vault(tmp_path):
    v = tmp_path / "vault"
    v.mkdir()
    cfg = LemoryConfig(vault=v)
    assert cfg.resolved_data_dir() == v / ".lemory"
    assert (v / ".lemory").is_dir()


def test_lemory_toml_discovery(tmp_path, monkeypatch):
    v = tmp_path / "vault"
    v.mkdir()
    (tmp_path / "lemory.toml").write_text(f'[lemory]\nvault = "{v}"\nchunk_chars = 999\n')
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert cfg.vault == v
    assert cfg.chunk_chars == 999


def test_kwargs_override_toml(tmp_path, monkeypatch):
    (tmp_path / "lemory.toml").write_text('[lemory]\nchunk_chars = 999\n')
    monkeypatch.chdir(tmp_path)
    assert load_config(chunk_chars=500).chunk_chars == 500


def test_env_overrides(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LEMORY_LLM_MODEL", "gemini-2.5-flash-lite")
    assert load_config().llm_model == "gemini-2.5-flash-lite"
