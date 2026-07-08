"""Tests for the qmd-inspired optional retrieval stages."""

from lemory.retrieval.search import expand_query, hybrid_search


def test_expand_query_returns_variants(engine):
    variants = expand_query(engine, "what did we decide about pricing", 2)
    assert 1 <= len(variants) <= 2
    assert all(isinstance(v, str) and v for v in variants)


def test_expand_query_failure_degrades(engine):
    engine.llm.generate_json = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("quota"))
    assert expand_query(engine, "anything", 2) == []


def test_search_with_expansion_still_finds_gold(engine):
    engine.index()
    hits = engine.search("what price per compute-minute did we decide", k=4, expand=True)
    assert hits and hits[0].title == "Mercury Initiative"


def test_search_with_rerank_runs_and_ranks(engine):
    engine.index()
    hits = engine.search("Dana Petrov favorite database", k=4, rerank=True)
    assert hits
    assert any(h.title == "Dana Petrov" for h in hits)


def test_rerank_failure_keeps_fusion_ranking(engine):
    engine.index()
    baseline = [h.chunk_id for h in engine.search("pricing pilot", k=4)]
    engine.llm.generate_json = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("quota"))
    with_broken_rerank = [h.chunk_id for h in engine.search("pricing pilot", k=4, rerank=True)]
    assert with_broken_rerank == baseline


def test_stages_default_off(engine):
    """Expansion/rerank must not fire unless enabled (they cost LLM calls)."""
    engine.index()
    before = engine.llm.calls["generate"]
    engine.search("pricing pilot", k=4)
    assert engine.llm.calls["generate"] == before


def test_baseline_modes_never_use_llm_stages(engine):
    engine.index()
    before = engine.llm.calls["generate"]
    engine.search("pricing", k=4, mode="vector", expand=True, rerank=True)
    engine.search("pricing", k=4, mode="bm25", expand=True, rerank=True)
    assert engine.llm.calls["generate"] == before
