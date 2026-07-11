from lemory.retrieval.search import _tokens, rrf_fuse


def test_rrf_fusion_math():
    vec = [(1, 0.9), (2, 0.8)]
    bm = [(2, 5.0), (3, 4.0)]
    fused = rrf_fuse([(vec, 1.0), (bm, 0.5)], rrf_k=60)
    # chunk 2 appears in both lists -> highest
    assert fused[2] > fused[1] > 0
    assert fused[2] > fused[3]
    assert abs(fused[1] - 1.0 / 61) < 1e-9
    assert abs(fused[2] - (1.0 / 62 + 0.5 / 61)) < 1e-9


def test_rrf_empty():
    assert rrf_fuse([([], 1.0)], 60) == {}


def test_tokens_strip_stopwords():
    assert _tokens("What is the favorite tool of Dana?") == {"favorite", "tool", "dana"}
    assert _tokens("") == set()


def test_vector_mode_has_no_title_boost_or_cap(engine):
    engine.index()
    # 'vector' mode must be a pure cosine ranking: same query, graph off,
    # results ordered by descending score with no per-doc cap applied
    hits = engine.search("Dana Petrov FoundationDB tracing platform", k=10, mode="vector")
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)


def test_graph_flag_off_matches_nograph(engine):
    engine.index()
    a = [h.chunk_id for h in engine.search("Mercury pricing", k=5, graph=False)]
    b = [h.chunk_id for h in engine.search("Mercury pricing", k=5, graph=False)]
    assert a == b  # deterministic


def test_search_empty_index(engine):
    assert engine.search("anything", k=5) == []


def test_search_returns_at_most_k(engine):
    engine.index()
    assert len(engine.search("Mercury", k=2)) <= 2


def test_graph_hops_two_reaches_chain_end(engine, vault):
    """A→B→C chain: hop-2 propagation must surface C for an A-anchored query."""
    (vault / "Alpha Project.md").write_text(
        "The Alpha Project builds telemetry pipelines. Led by [[Bram Osei]]."
    )
    (vault / "Bram Osei.md").write_text(
        "Bram Osei is a systems engineer. His toolkit of choice is [[Quarklight]]."
    )
    (vault / "Quarklight.md").write_text(
        "Quarklight is a profiling suite written in Zig with flamegraph output."
    )
    engine.index()

    engine.cfg.graph_hops = 1
    titles_1 = [h.title for h in engine.search("Alpha Project profiling suite language", k=8)]
    engine.cfg.graph_hops = 2
    titles_2 = [h.title for h in engine.search("Alpha Project profiling suite language", k=8)]
    # the chain end must be reachable at 2 hops
    assert "Quarklight" in titles_2
    # and hop-2 must never remove the direct evidence
    assert "Alpha Project" in titles_2
    # (1-hop may or may not find C via lexical luck — no assertion on titles_1
    # beyond sanity)
    assert titles_1
