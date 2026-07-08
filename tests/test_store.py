import numpy as np
import pytest

from lemory.store import Store, _fts_escape


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    yield s
    s.close()


def _add_doc(store, path, title, chunks, dim=8):
    doc_id = store.upsert_document(path, title, "h" + path, 0.0, [], {}, 0.0)
    rng = np.random.default_rng(len(path))
    vecs = rng.standard_normal((len(chunks), dim)).astype(np.float32)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
    store.replace_chunks(doc_id, title, chunks, vecs)
    return doc_id


def test_fts_escape_quotes_and_operators():
    assert _fts_escape('hello "world"') == '"hello" OR "world"'
    assert _fts_escape("a AND b OR c*") == '"a" OR "AND" OR "b" OR "OR" OR "c*"'
    assert _fts_escape("") == '""'
    assert _fts_escape("   ") == '""'


def test_bm25_handles_special_chars(store):
    _add_doc(store, "a.md", "A", [("", "the quick brown fox")])
    for q in ['fox "quick"', "fox)", "NEAR(fox", "fox*", "-fox", "한글 fox"]:
        store.bm25_search(q, 5)  # must not raise


def test_bm25_ranks_relevant_first(store):
    _add_doc(store, "a.md", "A", [("", "cats and dogs live together")])
    _add_doc(store, "b.md", "B", [("", "quantum entanglement of particles")])
    hits = store.bm25_search("quantum particles", 5)
    assert hits
    top = store.get_chunks([hits[0][0]])[hits[0][0]]
    assert top.title == "B"


def test_vector_search_empty_index(store):
    assert store.vector_search(np.zeros(8, dtype=np.float32), 5) == []


def test_vector_search_returns_topk_sorted(store):
    _add_doc(store, "a.md", "A", [("", f"c{i}") for i in range(20)])
    q = np.random.default_rng(0).standard_normal(8).astype(np.float32)
    q /= np.linalg.norm(q)
    hits = store.vector_search(q, 5)
    assert len(hits) == 5
    scores = [s for _, s in hits]
    assert scores == sorted(scores, reverse=True)


def test_chunk_sims_subset(store):
    d = _add_doc(store, "a.md", "A", [("", "one"), ("", "two"), ("", "three")])
    ids = store.doc_chunk_ids(d)
    q = np.ones(8, dtype=np.float32) / np.sqrt(8)
    sims = store.chunk_sims(q, ids[:2])
    assert set(sims) == set(ids[:2])
    assert store.chunk_sims(q, [999999]) == {}


def test_replace_chunks_updates_fts_and_matrix(store):
    d = _add_doc(store, "a.md", "A", [("", "alpha beta")])
    assert store.bm25_search("alpha", 5)
    rng = np.random.default_rng(1)
    v = rng.standard_normal((1, 8)).astype(np.float32)
    store.replace_chunks(d, "A", [("", "gamma delta")], v)
    assert not store.bm25_search("alpha", 5)
    assert store.bm25_search("gamma", 5)
    assert store.chunk_count() == 1


def test_delete_document_cascades(store):
    _add_doc(store, "a.md", "A", [("", "alpha beta")])
    store.delete_document("a.md")
    assert store.doc_count() == 0
    assert store.chunk_count() == 0
    assert store.bm25_search("alpha", 5) == []
    store.delete_document("nonexistent.md")  # no-op, no raise


def test_links_and_neighbors_undirected(store):
    a = _add_doc(store, "a.md", "A", [("", "x")])
    b = _add_doc(store, "b.md", "B", [("", "y")])
    store.replace_links(a, [(b, "wiki", 1.0)])
    assert (a, "wiki", 1.0) in store.neighbors([b])[b]
    assert (b, "wiki", 1.0) in store.neighbors([a])[a]
    store.replace_links(a, [])
    assert store.neighbors([a])[a] == []


def test_embed_cache_roundtrip(store):
    k = Store.cache_key("m", 8, "doc", "hello")
    v = np.arange(8, dtype=np.float32)
    store.cache_put_many({k: v})
    out = store.cache_get_many([k, "missing"])
    assert np.allclose(out[k], v)
    assert "missing" not in out
    # deterministic + distinct per task/text
    assert Store.cache_key("m", 8, "doc", "hello") == k
    assert Store.cache_key("m", 8, "query", "hello") != k


def test_entity_links(store):
    a = _add_doc(store, "a.md", "A", [("", "x")])
    b = _add_doc(store, "b.md", "B", [("", "y")])
    c = _add_doc(store, "c.md", "C", [("", "z")])
    store.add_entity_mentions(a, ["Kafka", "Redis"])
    store.add_entity_mentions(b, ["kafka"])  # case-insensitive merge
    store.add_entity_mentions(c, [""])  # ignored
    n = store.rebuild_entity_links()
    assert n == 1
    nbrs = store.neighbors([a])[a]
    assert any(dst == b and kind == "entity" for dst, kind, _ in nbrs)


def test_title_map_includes_aliases(store):
    store.upsert_document("a.md", "Real Title", "h", 0.0, [], {"aliases": ["Nick", "Other"]}, 0.0)
    tm = store.title_map()
    assert tm["real title"] == tm["nick"] == tm["other"]


def test_meta_roundtrip(store):
    assert store.get_meta("nope") is None
    store.set_meta("k", "v")
    assert store.get_meta("k") == "v"


def test_upsert_document_is_idempotent(store):
    id1 = store.upsert_document("a.md", "A", "h1", 0.0, [], {}, 0.0)
    id2 = store.upsert_document("a.md", "A2", "h2", 1.0, ["t"], {}, 1.0)
    assert id1 == id2
    assert store.doc_count() == 1
    assert store.get_doc_by_path("a.md").title == "A2"
