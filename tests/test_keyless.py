"""Keyless mode: no API key, no fastembed — Lemory still indexes and searches
(lexical leg only), and upgrades in place when a key appears."""

import sys

import pytest

from lemory.config import LemoryConfig
from lemory.engine import Engine


@pytest.fixture
def keyless_engine(vault, tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setitem(sys.modules, "fastembed", None)  # import raises
    cfg = LemoryConfig(vault=vault, data_dir=tmp_path / "data")
    eng = Engine(cfg)
    yield eng
    eng.close()


def test_keyless_index_and_search(keyless_engine):
    eng = keyless_engine
    assert eng.keyless
    rep = eng.index()
    assert rep.chunks > 0 and rep.embedded == 0
    hits = eng.search("pricing decision", k=3)
    assert hits and hits[0].title == "Mercury Initiative"
    # typo repair and operators are lexical — they survive keylessness
    assert eng.search("pricng decision", k=3)
    assert all(h.title == "Weekly Log" for h in eng.search("tag:log pricing", k=3))


def test_keyless_plan_and_status(keyless_engine):
    eng = keyless_engine
    plan = eng.index_plan()
    assert plan.embeds_needed == 0
    assert "unconfigured" in eng.status()["embed_model"]


def test_key_upgrade_embeds_via_documented_incremental_flow(vault, tmp_path, monkeypatch):
    """The README promises adding a key upgrades in place. The DOCUMENTED flow
    is a plain `lemory index` (incremental) after the key appears — NOT
    index(full=True). Regression: an incremental sync used to only embed
    changed files, leaving keyless-era notes permanently vectorless."""
    from conftest import DIM, FakeGemini

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setitem(sys.modules, "fastembed", None)
    cfg = LemoryConfig(vault=vault, data_dir=tmp_path / "data")
    eng = Engine(cfg)
    eng.index()
    assert eng.store._embedded_count() == 0
    total = eng.store.chunk_count()
    assert total > 0

    eng.cfg.gemini_api_key = "test"
    eng.cfg.embed_dim = DIM
    eng._llm = FakeGemini()
    assert not eng.keyless

    rep = eng.index()  # incremental — no file changed since the keyless index
    assert eng.store.unembedded_chunk_count() == 0, "old notes left vectorless"
    assert eng.store._embedded_count() == total and rep.embedded == total
    hits = eng.search("pricing decision", k=3)
    assert hits and hits[0].title == "Mercury Initiative"
    eng.close()
