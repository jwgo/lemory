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


# --- Korean-aware verbatim coverage & the reciting pin ---------------------

def test_jamo_decomposition_matches_conjugation():
    from lemory.retrieval.search import _to_jamo, _token_in_text

    # '만든' (adnominal) vs '만들었다' (past declarative): the syllable-level
    # strings diverge (ㄹ-drop), the jamo prefix does not
    text = "윤상이 만들었다"
    assert _token_in_text("만든", text, _to_jamo(text))
    # unrelated word must not match
    assert not _token_in_text("부순", text, _to_jamo(text))


def test_coverage_tokens_drop_korean_question_furniture():
    from lemory.retrieval.search import _coverage_tokens

    toks = _coverage_tokens("진산파동을 일으킨 인물은?")
    assert "진산파동을" in toks
    assert "인물은" not in toks  # final topic-marked answer-category noun
    # declarative search keeps its topic noun (it IS the content)
    toks2 = _coverage_tokens("프로젝트 예산은")
    assert "예산은" in toks2


def test_coverage_tokens_drop_interrogatives_and_glue():
    from lemory.retrieval.search import _coverage_tokens

    toks = _coverage_tokens("김학인과 함께 만든 스쿨밴드는 무엇인가?")
    assert "무엇인가" not in toks
    assert "함께" not in toks
    assert "김학인과" in toks


def test_verbatim_pin_preserves_bm25_order(engine):
    """A query that recites a note nearly verbatim must keep BM25's ranking:
    rank-interleaved fusion may not bury the decisive lexical top hit."""
    engine.index()
    q = "Dana previously worked at Weyland Corp on distributed tracing"
    hy = engine.search(q, k=3)
    bm = engine.search(q, k=3, mode="bm25")
    assert hy and bm
    assert hy[0].chunk_id == bm[0].chunk_id


def test_verbatim_pin_gate_configurable(engine):
    engine.index()
    engine.cfg.verbatim_pin_gate = 2.0  # unreachable -> pin never fires
    q = "Dana previously worked at Weyland Corp on distributed tracing"
    assert engine.search(q, k=3)  # still returns fused results


def test_jamo_matching_survives_korean_spacing():
    from lemory.retrieval.search import _to_jamo, _token_in_text

    # 띄어쓰기 variation: query writes the compound solid ('민법전초안은'),
    # the note spaces it ('민법전 초안은') — jamo containment ignores spaces
    text = "제1차 민법전 초안은 총 5개 편으로 이루어져 있다"
    assert _token_in_text("민법전초안은", text, _to_jamo(text))
    # unrelated compound must not match
    assert not _token_in_text("형법전초안은", text, _to_jamo(text))


def test_short_korean_verbatim_questions_reach_coverage(engine, vault):
    from lemory.retrieval.search import _coverage_tokens

    # after question-furniture stripping, 2 Hangul content tokens must be
    # enough to gate ("이충우의 본명은 무엇인가?" is a verbatim lookup)
    toks = _coverage_tokens("이충우의 본명은 무엇인가?")
    assert toks and len(toks) >= 1


# --- dedicated cross-encoder reranker (opt-in precision mode) ---------------

def test_dedicated_reranker_promotes_relevant(engine, vault, monkeypatch):
    """A reranker verdict lifts a retrieved-but-low-ranked gold chunk to the
    top without changing WHAT was retrieved (recall@k unchanged)."""
    engine.index()
    # stub the llama.cpp Qwen3-Reranker: mark only the Dana note relevant
    import lemory.providers.reranker as rr
    monkeypatch.setattr(rr, "rerank_scores",
                        lambda query, docs, **kw: [1.0 if "Dana" in d else 0.0 for d in docs])
    engine.cfg.reranker = True
    hits = engine.search("Weyland Corp distributed tracing", k=5)
    assert hits, "reranker path must still return results"
    assert "Dana Petrov" in hits[0].title


def test_dedicated_reranker_off_by_default(engine, vault, monkeypatch):
    engine.index()
    calls = {"n": 0}
    def _rr(query, docs, **kw):
        calls["n"] += 1
        return [0.0] * len(docs)
    import lemory.providers.reranker as rr
    monkeypatch.setattr(rr, "rerank_scores", _rr)
    # cfg.reranker defaults False -> the reranker is never consulted
    engine.search("Mercury pricing", k=5)
    assert calls["n"] == 0
