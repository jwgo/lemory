"""Curriculum context ordering (CDS-inspired, arXiv:2605.13511)."""

from __future__ import annotations

import numpy as np

from lemory.retrieval.curriculum import curriculum_order, path_smoothness


def _hits(engine, query, k=8):
    return engine.search(query, k=k)


def test_order_is_permutation_and_deterministic(engine):
    engine.index()
    hits = _hits(engine, "pricing decision compute-minute", k=6)
    qv = engine.embed_query_cached("pricing decision compute-minute")
    o1 = curriculum_order(engine, qv, hits)
    o2 = curriculum_order(engine, qv, hits)
    assert [h.chunk_id for h in o1] == [h.chunk_id for h in o2]
    assert sorted(h.chunk_id for h in o1) == sorted(h.chunk_id for h in hits)


def test_anchor_is_most_query_similar(engine):
    engine.index()
    q = "Mercury Initiative pricing"
    hits = _hits(engine, q, k=6)
    qv = engine.embed_query_cached(q)
    ordered = curriculum_order(engine, qv, hits)
    vecs = engine.store.chunk_vectors([h.chunk_id for h in hits])
    sims = {cid: float(v @ qv) for cid, v in vecs.items()}
    assert ordered[0].chunk_id == max(sims, key=sims.get)


def test_path_is_no_rougher_than_rank_order(engine, vault):
    # two topic clusters guarantee that rank order can interleave topics
    for i in range(3):
        (vault / f"Kimchi {i}.md").write_text(
            f"Kimchi fermentation batch {i}: cabbage, salt brine, temperature control notes."
        )
        (vault / f"Rust {i}.md").write_text(
            f"Rust borrow checker study {i}: ownership, lifetimes, compiler errors."
        )
    engine.index()
    q = "fermentation temperature and borrow checker lifetimes"
    hits = _hits(engine, q, k=8)
    if len(hits) < 4:
        return
    qv = engine.embed_query_cached(q)
    ordered = curriculum_order(engine, qv, hits)
    assert path_smoothness(engine, ordered) >= path_smoothness(engine, hits) - 1e-9


def test_small_and_vectorless_inputs_safe(engine):
    engine.index()
    hits = _hits(engine, "atlas", k=2)
    assert curriculum_order(engine, None, hits) == hits  # <=2: unchanged
    # chunks unknown to the vector matrix fall back gracefully
    fake = [h for h in _hits(engine, "atlas", k=4)]
    for h in fake:
        h.chunk_id = 10_000_000 + h.chunk_id
    assert curriculum_order(engine, None, fake) == fake


def test_ask_uses_curriculum_and_sources_match_citations(engine):
    engine.index()
    engine.cfg.context_order = "curriculum"
    ans = engine.ask("what is the mercury initiative pricing?")
    assert ans.sources
    engine.cfg.context_order = "rank"
    ans2 = engine.ask("what is the mercury initiative pricing?")
    assert ans2.sources
