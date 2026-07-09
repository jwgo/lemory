"""Local (keyless) provider: config resolution and search-only guidance.

The real fastembed model isn't downloaded in CI — embedding calls are faked;
what's under test is provider resolution, dim plumbing, and ask() guidance.
"""

import numpy as np
import pytest

from lemory.config import LemoryConfig
from lemory.engine import Engine
from lemory.providers.local import LOCAL_EMBED_DIM, LocalClient


def test_provider_local_explicit(tmp_path):
    cfg = LemoryConfig(vault=tmp_path, provider="local")
    assert cfg.resolved_provider() == "local"
    assert cfg.active_embed_dim() == LOCAL_EMBED_DIM
    assert "multilingual" in cfg.active_embed_model()


def test_auto_falls_back_to_local_without_keys(tmp_path, monkeypatch):
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    cfg = LemoryConfig(vault=tmp_path)  # fastembed installed in this env
    assert cfg.resolved_provider() == "local"


def test_local_ask_raises_helpfully_without_llm(tmp_path, vault, monkeypatch):
    client = LocalClient()
    monkeypatch.setattr(
        LocalClient, "_embedder",
        lambda self: type("E", (), {"embed": staticmethod(
            lambda texts: [np.ones(LOCAL_EMBED_DIM, dtype=np.float32) for _ in texts])})(),
    )
    cfg = LemoryConfig(vault=vault, data_dir=tmp_path / "d", provider="local")
    eng = Engine(cfg, llm=client)
    eng.index()
    assert eng.search("mercury", k=2)  # search works keyless
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        eng.ask("what is mercury?")
    eng.close()


def test_local_with_gemini_generator_uses_it(tmp_path):
    class FakeGen:
        llm_model = "fake"
        def generate(self, prompt, system=None, **kw): return "generated!"
        def generate_json(self, prompt, system=None, **kw): return {}
        def close(self): pass

    client = LocalClient(generator=FakeGen())
    assert client.generate("hi") == "generated!"
