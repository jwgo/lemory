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
    cfg = LemoryConfig(vault=tmp_path, provider="local",
                       local_embed_backend="fastembed")
    assert cfg.resolved_provider() == "local"
    assert cfg.active_embed_dim() == LOCAL_EMBED_DIM
    assert "multilingual" in cfg.active_embed_model()


def test_local_backend_llamacpp_resolution_and_dispatch(tmp_path):
    """The llama.cpp/Harrier local backend: 1024d, a distinct model id, and the
    factory routes to it without loading the (lazy) GGUF."""
    cfg = LemoryConfig(vault=tmp_path, provider="local",
                       local_embed_backend="llamacpp")
    assert cfg.resolved_local_backend() == "llamacpp"
    assert cfg.active_embed_dim() == 1024
    assert cfg.active_embed_model().startswith("llamacpp:")
    assert "harrier" in cfg.active_embed_model().lower()

    from lemory.providers import create_client

    client = create_client(cfg)
    assert type(client).__name__ == "LlamaCppLocalClient"
    assert client.embed_dim == 1024
    client.close()


def test_auto_falls_back_to_local_without_keys(tmp_path, monkeypatch):
    import pytest
    pytest.importorskip("fastembed", reason="pip install 'lemory[local]'")
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


def test_embed_raises_actionable_error_when_e5_onnx_unavailable(monkeypatch):
    """If the community e5-ko ONNX repo is unreachable, embedding raises a clear,
    actionable error (naming the bundled MiniLM fallback + `index --full`) rather
    than silently swapping models — an auto-swap is invisible to the embed cache
    signature and would mix vectors under e5 keys with no recovery."""
    import fastembed

    from lemory.providers import local as L

    monkeypatch.setattr(L, "_REGISTERED", set())  # isolate module-global registry

    class FakeTE:
        def __init__(self, model_name):
            raise RuntimeError("HF repo 404")

    monkeypatch.setattr(fastembed, "TextEmbedding", FakeTE)
    c = LocalClient(embed_model=L.DEFAULT_EMBED_MODEL)
    with pytest.raises(RuntimeError) as ei:
        c.embed(["안녕하세요"])
    msg = str(ei.value)
    assert L._FALLBACK_EMBED_MODEL in msg and "index --full" in msg
    assert c.embed_model == L.DEFAULT_EMBED_MODEL  # never silently reassigned
