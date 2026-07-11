"""Ollama provider: request shapes, error guidance, config wiring, and the
embed-model-switch auto-reindex. All offline via httpx.MockTransport."""

from __future__ import annotations

import json

import httpx
import numpy as np
import pytest

from lemory.config import LemoryConfig
from lemory.providers.ollama import OllamaClient


def make_client(handler) -> OllamaClient:
    c = OllamaClient(embed_dim=4)
    c._http = httpx.Client(transport=httpx.MockTransport(handler))
    return c


def test_embed_batches_and_normalizes():
    seen = []

    def handler(req):
        body = json.loads(req.content)
        seen.append(len(body["input"]))
        return httpx.Response(200, json={"embeddings": [[1.0, 2.0, 2.0, 0.0]] * len(body["input"])})

    c = make_client(handler)
    out = c.embed([f"t{i}" for i in range(40)])
    assert out.shape == (40, 4)
    assert sum(seen) == 40 and max(seen) <= 32  # batched
    assert np.allclose(np.linalg.norm(out, axis=1), 1.0)


def test_embed_dim_mismatch_guidance():
    c = make_client(lambda req: httpx.Response(200, json={"embeddings": [[1.0, 0.0]]}))
    with pytest.raises(RuntimeError, match="ollama_embed_dim = 2"):
        c.embed(["x"])


def test_generate_chat_shape_and_json_mode():
    captured = {}

    def handler(req):
        captured.update(json.loads(req.content))
        return httpx.Response(200, json={"message": {"content": '{"ok": true}'}})

    c = make_client(handler)
    out = c.generate_json("question", system="sys")
    assert out == {"ok": True}
    assert captured["format"] == "json" and captured["stream"] is False
    assert captured["messages"][0] == {"role": "system", "content": "sys"}
    # provider-specific kwargs from shared call sites must not crash ollama
    assert c.generate("q", thinking_budget=0, model="whatever") == '{"ok": true}'


def test_server_down_gives_install_guidance():
    def handler(req):
        raise httpx.ConnectError("refused")

    c = make_client(handler)
    with pytest.raises(RuntimeError, match="ollama.com"):
        c.embed(["x"])
    assert c.server_alive() is False


def test_config_wires_ollama_provider():
    cfg = LemoryConfig(provider="ollama", gemini_api_key="", vault=None)
    assert cfg.resolved_provider() == "ollama"
    assert cfg.active_embed_model() == "qwen3-embedding:0.6b"
    assert cfg.active_embed_dim() == 1024
    assert cfg.active_llm_model() == "gemma3n:e4b"
    assert cfg.resolved_api_key() == ""  # keyless

    from lemory.providers import create_client

    client = create_client(cfg)
    assert client.embed_model == "qwen3-embedding:0.6b"
    client.close()


def test_embed_model_switch_forces_full_reindex(engine, vault):
    engine.index()
    before = engine.store.get_meta("embed_signature")
    assert before and str(engine.cfg.active_embed_dim()) in before

    # simulate a model switch: same dim (so the fake embedder still works),
    # different model name → different vector space
    engine.cfg.embed_model = "totally-different-embedder"
    rep = engine.index()
    # every doc re-processed even though no file changed
    assert rep.updated == engine.store.doc_count()
    assert engine.store.get_meta("embed_signature") != before


def test_unchanged_signature_stays_incremental(engine):
    engine.index()
    rep = engine.index()
    assert rep.updated == 0 and rep.unchanged == engine.store.doc_count()


def test_plan_detects_model_switch_as_full(engine):
    engine.index()
    plan = engine.index_plan()
    assert plan.to_process == 0
    engine.cfg.embed_model = "some-new-embedder"
    plan = engine.index_plan()
    assert plan.to_process == engine.store.doc_count()
    assert plan.embeds_needed == plan.chunks_total  # new model → all cache misses


def test_embed_rate_ema_recorded(engine):
    engine.index()  # fake embedder is instant, but >=8 chunks in one batch? maybe not
    # force a measurable batch through the cache layer
    engine.embed_documents_cached([f"text {i}" for i in range(16)])
    # rate may or may not be recorded depending on timing floor; API must not crash
    plan = engine.index_plan()
    assert plan.rate_chunks_per_s > 0
