"""IVF-int8 ANN index: recall vs exact search, persistence, store routing."""

import numpy as np
import pytest

from lemory.storage import Store
from lemory.storage.ann import IVFFlatIndex


def _clustered(n, dim, n_clusters=32, seed=7):
    """Unit vectors with realistic cluster structure (embeddings are never
    uniform on the sphere)."""
    rng = np.random.default_rng(seed)
    centers = rng.standard_normal((n_clusters, dim)).astype(np.float32)
    centers /= np.linalg.norm(centers, axis=1, keepdims=True)
    which = rng.integers(n_clusters, size=n)
    x = centers[which] + 0.35 * rng.standard_normal((n, dim)).astype(np.float32)
    x /= np.linalg.norm(x, axis=1, keepdims=True)
    return x


def _blocks(x, ids, block=1000):
    for i in range(0, len(x), block):
        yield x[i:i + block], ids[i:i + block]


def _exact_topk(x, ids, q, k):
    sims = x @ q
    top = np.argsort(-sims)[:k]
    return [int(ids[i]) for i in top]


def test_ivf_recall_vs_exact():
    # correctness check on a deliberately hard corpus (heavily overlapping
    # low-dim clusters — much worse than real embedding manifolds, where
    # recall@10 measures 0.97 at 2% scanned; see BENCHMARKS.md §scale)
    n, dim = 6000, 32
    x = _clustered(n, dim)
    ids = np.arange(100, 100 + n, dtype=np.int64)
    idx = IVFFlatIndex.build(_blocks(x, ids), total=n, dim=dim, nlist=154)
    rng = np.random.default_rng(3)
    recalls = []
    for _ in range(20):
        q = x[rng.integers(n)] + 0.1 * rng.standard_normal(dim).astype(np.float32)
        q /= np.linalg.norm(q)
        got = {cid for cid, _ in idx.search(q, 10, nprobe=64)}
        want = set(_exact_topk(x, ids, q, 10))
        recalls.append(len(got & want) / 10)
    assert np.mean(recalls) >= 0.95, f"mean recall@10 {np.mean(recalls):.3f}"


def test_ivf_scores_close_to_true_cosine():
    n, dim = 2000, 16
    x = _clustered(n, dim)
    ids = np.arange(n, dtype=np.int64)
    idx = IVFFlatIndex.build(_blocks(x, ids), total=n, dim=dim)
    q = x[0]
    for cid, sim in idx.search(q, 5, nprobe=16):
        true = float(x[cid] @ q)
        assert abs(sim - true) < 0.02  # int8 quantization error bound


def test_ivf_dim_mismatch_and_empty():
    idx = IVFFlatIndex.build(iter([]), total=0, dim=8)
    assert idx.search(np.ones(8, dtype=np.float32), 5) == []
    n, dim = 500, 8
    x = _clustered(n, dim)
    idx = IVFFlatIndex.build(_blocks(x, np.arange(n, dtype=np.int64)), total=n, dim=dim)
    assert idx.search(np.ones(16, dtype=np.float32), 5) == []


def test_ivf_persistence_roundtrip(tmp_path):
    n, dim = 1000, 16
    x = _clustered(n, dim)
    ids = np.arange(n, dtype=np.int64)
    idx = IVFFlatIndex.build(_blocks(x, ids), total=n, dim=dim)
    p = tmp_path / "ann.npz"
    idx.save(p, "fp-1")
    loaded = IVFFlatIndex.load(p, "fp-1")
    assert loaded is not None and loaded.size == n
    q = x[42]
    assert idx.search(q, 5) == loaded.search(q, 5)
    assert IVFFlatIndex.load(p, "fp-other") is None       # stale fingerprint
    assert IVFFlatIndex.load_any(p).size == n             # centroid salvage path


def test_ivf_centroid_reuse_build():
    n, dim = 1200, 16
    x = _clustered(n, dim)
    ids = np.arange(n, dtype=np.int64)
    first = IVFFlatIndex.build(_blocks(x[:1000], ids[:1000]), total=1000, dim=dim)
    grown = IVFFlatIndex.build(_blocks(x, ids), total=n, dim=dim,
                               centroids=first.centroids, scale=first.scale)
    assert grown.size == n
    q = x[1100]
    got = {cid for cid, _ in grown.search(q, 10, nprobe=16)}
    want = set(_exact_topk(x, ids, q, 10))
    assert len(got & want) >= 7


def test_rows_for_dequantizes():
    n, dim = 800, 16
    x = _clustered(n, dim)
    ids = np.arange(n, dtype=np.int64)
    idx = IVFFlatIndex.build(_blocks(x, ids), total=n, dim=dim)
    rows = idx.rows_for([0, 5, 999999])
    assert set(rows) == {0, 5}
    assert np.abs(rows[5] - x[5]).max() < 0.02


# ---------------------------------------------------------------- store level

def _fill_store(store, n_docs=30, chunks_per_doc=10, dim=8, seed=11):
    rng = np.random.default_rng(seed)
    for d in range(n_docs):
        doc_id = store.upsert_document(f"d{d}.md", f"D{d}", f"h{d}", 0.0, [], {}, 0.0)
        chunks = [("", f"doc {d} chunk {i}") for i in range(chunks_per_doc)]
        vecs = rng.standard_normal((chunks_per_doc, dim)).astype(np.float32)
        vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
        store.replace_chunks(doc_id, f"D{d}", chunks, vecs)


def test_store_switches_to_ann_above_threshold(tmp_path):
    s = Store(tmp_path / "t.db", ann_threshold=100, ann_nprobe=64)
    try:
        _fill_store(s, n_docs=30, chunks_per_doc=10)  # 300 chunks > 100
        assert s.vector_index_kind() == "ivf-int8"
        q = np.ones(8, dtype=np.float32) / np.sqrt(8)
        hits = s.vector_search(q, 5)
        assert len(hits) == 5
        scores = [x for _, x in hits]
        assert scores == sorted(scores, reverse=True)
        # ANN top-1 must agree with the exact scan at generous nprobe
        exact = Store(tmp_path / "e.db", ann_threshold=10**9)
        _fill_store(exact, n_docs=30, chunks_per_doc=10)
        assert hits[0][0] == exact.vector_search(q, 1)[0][0]
        exact.close()
        # chunk_sims must work without the float32 matrix
        ids = s.doc_chunk_ids(1)
        sims = s.chunk_sims(q, ids[:3])
        assert set(sims) == set(ids[:3])
    finally:
        s.close()


def test_store_stays_exact_below_threshold(tmp_path):
    s = Store(tmp_path / "t.db", ann_threshold=10_000)
    try:
        _fill_store(s, n_docs=5, chunks_per_doc=4)
        assert s.vector_index_kind() == "exact"
        assert len(s.vector_search(np.ones(8, dtype=np.float32), 3)) == 3
    finally:
        s.close()


def test_store_ann_persists_and_invalidates(tmp_path):
    s = Store(tmp_path / "t.db", ann_threshold=100)
    try:
        _fill_store(s, n_docs=30, chunks_per_doc=10)
        s.vector_search(np.ones(8, dtype=np.float32), 3)  # triggers build+save
        assert (tmp_path / "ann-index.npz").exists()
        # editing a doc invalidates and rebuilds with a fresh fingerprint
        rng = np.random.default_rng(5)
        v = rng.standard_normal((1, 8)).astype(np.float32)
        v /= np.linalg.norm(v)
        s.replace_chunks(1, "D0", [("", "changed")], v)
        hits = s.vector_search(v[0], 1)
        assert hits and s.get_chunks([hits[0][0]])[hits[0][0]].text == "changed"
    finally:
        s.close()


def test_store_ann_reloads_from_disk(tmp_path):
    s = Store(tmp_path / "t.db", ann_threshold=100)
    _fill_store(s, n_docs=30, chunks_per_doc=10)
    q = np.ones(8, dtype=np.float32) / np.sqrt(8)
    first = s.vector_search(q, 5)
    s.close()
    s2 = Store(tmp_path / "t.db", ann_threshold=100)
    try:
        assert s2.vector_search(q, 5) == first  # loaded, not retrained
    finally:
        s2.close()


def test_store_ann_build_failure_falls_back(tmp_path, monkeypatch):
    """A build OOM/error must fall back to exact search and NOT retry on every
    query (which would re-OOM forever)."""
    import lemory.storage.ann as annmod

    s = Store(tmp_path / "t.db", ann_threshold=50)
    _fill_store(s, n_docs=40, chunks_per_doc=10)
    (tmp_path / "ann-index.npz").unlink(missing_ok=True)

    calls = {"n": 0}
    orig = annmod.IVFFlatIndex.build

    def boom(*a, **k):
        calls["n"] += 1
        raise MemoryError("simulated OOM")

    monkeypatch.setattr(annmod.IVFFlatIndex, "build", staticmethod(boom))
    q = np.ones(8, dtype=np.float32) / np.sqrt(8)
    hits = [s.vector_search(q, 5) for _ in range(3)]
    assert calls["n"] == 1, "must not rebuild after a failure"
    assert all(len(h) == 5 for h in hits), "exact fallback must still return results"
    # new data clears the failure flag so a smaller build can be retried
    monkeypatch.setattr(annmod.IVFFlatIndex, "build", staticmethod(orig))
    rng = np.random.default_rng(9)
    v = rng.standard_normal((1, 8)).astype(np.float32)
    v /= np.linalg.norm(v)
    s.replace_chunks(1, "D0", [("", "changed")], v)
    assert len(s.vector_search(q, 5)) == 5  # rebuilds cleanly now
    s.close()


def test_store_ann_build_streams_not_materialized(tmp_path):
    """The store must pass a re-iterable factory to build (streaming), not a
    one-shot generator — otherwise training's two passes would need list()."""
    s = Store(tmp_path / "t.db", ann_threshold=50)
    _fill_store(s, n_docs=40, chunks_per_doc=10)
    assert s.vector_index_kind() == "ivf-int8"
    # if the factory weren't re-iterable, the 2-pass k-means build would raise
    assert len(s.vector_search(np.ones(8, dtype=np.float32) / np.sqrt(8), 5)) == 5
    s.close()
