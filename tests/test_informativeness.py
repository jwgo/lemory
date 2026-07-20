"""Informativeness prior: on all-boilerplate queries the vector leg is
re-weighted by rare-content, so a fact line outranks chat filler that quotes
the query's own words. Measured on RoleMemQA-messy episodic; these tests pin
the mechanism offline (no embeddings)."""
import numpy as np

from lemory.retrieval.search import _apply_informativeness, _rare_content_frac
from lemory.storage import Store


def test_rare_content_frac_separates_fact_from_filler():
    # a fact line is mostly rare corpus content; filler is all common words
    term_doc = {"약속": 200, "기억해": 180, "둘게": 150,  # boilerplate
                "장마": 1, "자전거": 1, "여행": 2}         # the specific event
    ceiling = 3.0
    fact = _rare_content_frac("우리 약속 하나 하자 장마 끝나면 자전거 여행 가기", term_doc, ceiling)
    filler = _rare_content_frac("기억해 둘게 약속", term_doc, ceiling)
    assert fact > filler
    assert filler == 0.0  # no rare token at all


def test_rare_content_frac_unknown_terms_count_as_rare():
    # a term the corpus never saw (df 0) is discriminative by definition
    assert _rare_content_frac("문브릿지", {}, 3.0) == 1.0


def test_apply_informativeness_reorders_near_ties(tmp_path):
    store = Store(tmp_path / "t.db")
    vecs = np.ones((1, 4), dtype=np.float32)
    # two near-identical chat sessions; only 'fact.md' carries a rare event
    store.store_note("filler.md", "filler", "h1", 0.0, [], {}, 0.0, [],
                     [("", "기억해 둘게 약속 잘 지내 고마워")], vecs)
    store.store_note("fact.md", "fact", "h2", 1.0, [], {}, 1.0, [],
                     [("", "우리 약속 하나 하자 장마 끝나면 자전거 여행 가기")], vecs)
    fill_cid = store.doc_chunk_ids(store.get_doc_by_path("filler.md").id)[0]
    fact_cid = store.doc_chunk_ids(store.get_doc_by_path("fact.md").id)[0]

    # a realistic corpus df map (a 2-chunk store makes everything rare): the
    # chat words are common, only the event words are rare
    term_doc = {"기억해": 50, "둘게": 50, "약속": 50, "고마워": 50, "지내": 50,
                "우리": 40, "하나": 40, "하자": 30, "끝나면": 25, "가기": 30,
                "장마": 1, "자전거": 1, "여행": 2}
    # filler ranks first by a hair before the prior; the prior flips it
    hits = [(fill_cid, 0.61), (fact_cid, 0.60)]
    out = _apply_informativeness(store, hits, prior=1.0, term_doc=term_doc, ceiling=3.0)
    assert out[0][0] == fact_cid
    store.close()


def test_chunk_doc_freq_populated_from_fts_vocab(tmp_path):
    store = Store(tmp_path / "t.db")
    vecs = np.ones((1, 4), dtype=np.float32)
    store.store_note("a.md", "a", "h", 0.0, [], {}, 0.0, [],
                     [("", "장마 자전거 여행 약속")], vecs)
    td = store.chunk_doc_freq()
    assert td  # fts5vocab table exists and is readable
    assert td.get("자전거", 0) >= 1
    store.close()


def test_apply_informativeness_no_prior_is_noop(tmp_path):
    store = Store(tmp_path / "t.db")
    vecs = np.ones((1, 4), dtype=np.float32)
    store.store_note("a.md", "a", "h", 0.0, [], {}, 0.0, [], [("", "장마 자전거 여행")], vecs)
    cid = store.doc_chunk_ids(store.get_doc_by_path("a.md").id)[0]
    hits = [(cid, 0.5)]
    # prior 0 leaves order and identity untouched
    assert _apply_informativeness(store, hits, 0.0, store.chunk_doc_freq(), 2.0) == hits
    store.close()
