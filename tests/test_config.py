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


def test_keyless_resolves_to_local(monkeypatch):
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    cfg = LemoryConfig()
    # fastembed is installed in this environment -> keyless falls back to local
    assert cfg.resolved_provider() == "local"
    assert cfg.resolved_api_key() == ""  # local embeddings need no key


def test_api_key_from_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k1")
    assert LemoryConfig().resolved_api_key() == "k1"


def test_provider_auto_prefers_gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    cfg = LemoryConfig()
    assert cfg.resolved_provider() == "gemini"
    assert cfg.active_embed_model() == cfg.embed_model


def test_provider_auto_falls_back_to_openai(monkeypatch):
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    cfg = LemoryConfig()
    assert cfg.resolved_provider() == "openai"
    assert cfg.resolved_api_key() == "o"
    assert cfg.active_embed_model() == cfg.openai_embed_model
    assert cfg.active_llm_model() == cfg.openai_llm_model


def test_provider_explicit_override(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    cfg = LemoryConfig(provider="openai")
    assert cfg.resolved_provider() == "openai"
    assert cfg.resolved_api_key() == "o"


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
