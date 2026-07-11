"""Vector-index scale benchmark: exact float32 scan vs IVF-int8 (storage/ann.py).

The honest question this answers: "SQLite + numpy — does it fall over on a
huge vault?" Method:

* Base vectors are REAL gemini-embedding-001 768d embeddings pooled from the
  other benchmarks' embed caches (~5k unique). Purely random synthetic vectors
  are the worst case for IVF and misrepresent real corpora; real embeddings
  live on an anisotropic manifold.
* Scale-up preserves that manifold: new points are SLERP interpolations
  between a real point and one of its true 8 nearest neighbors, plus 2%
  jitter, re-normalized. Labelled semi-synthetic accordingly.
* Queries are held-out real vectors with 5% perturbation.
* Recall@10 is measured against the exact float32 scan on the same corpus.

Run:  python benchmarks/bench_scale.py [n ...]     (default: 50k 200k 1M)
"""

from __future__ import annotations

import glob
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from lemory.storage.ann import IVFFlatIndex, _auto_nlist  # noqa: E402

WORK = Path(__file__).resolve().parent / "work"


def load_real_vectors() -> np.ndarray:
    vecs = {}
    for db in glob.glob(str(WORK / "*/lemory.db")):
        c = sqlite3.connect(db)
        try:
            for key, blob in c.execute("SELECT key, vec FROM embed_cache"):
                v = np.frombuffer(blob, dtype=np.float32)
                if v.shape[0] == 768:
                    vecs[key] = v
        finally:
            c.close()
    if len(vecs) < 1000:
        raise SystemExit("need embed caches from the other benchmarks first "
                         "(run run_bench.py / run_real_bench.py)")
    base = np.vstack(list(vecs.values()))
    return base / np.linalg.norm(base, axis=1, keepdims=True)


def scale_up(base: np.ndarray, target: int, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    sims = base @ base.T
    np.fill_diagonal(sims, -1)
    nn8 = np.argpartition(-sims, 8, axis=1)[:, :8]
    out = [base]
    need = target - len(base)
    while need > 0:
        m = min(need, len(base))
        i = rng.permutation(len(base))[:m]
        j = nn8[i, rng.integers(8, size=m)]
        t = rng.uniform(0.15, 0.85, size=(m, 1)).astype(np.float32)
        x = (1 - t) * base[i] + t * base[j]
        x += 0.02 * rng.standard_normal(x.shape).astype(np.float32)
        x /= np.linalg.norm(x, axis=1, keepdims=True)
        out.append(x)
        need -= m
    return np.vstack(out)[:target]


def blocks(x, ids, b=20_000):
    for i in range(0, len(x), b):
        yield x[i:i + b], ids[i:i + b]


def run(n: int, nprobes=(16, 32, 48, 96), n_queries: int = 40) -> None:
    base = load_real_vectors()
    x = scale_up(base, n)
    ids = np.arange(n, dtype=np.int64)
    rng = np.random.default_rng(42)
    qi = rng.permutation(len(base))[:n_queries]
    queries = base[qi] + 0.05 * rng.standard_normal((n_queries, 768)).astype(np.float32)
    queries /= np.linalg.norm(queries, axis=1, keepdims=True)

    t0 = time.perf_counter()
    idx = IVFFlatIndex.build(blocks(x, ids), total=n, dim=768)
    build_s = time.perf_counter() - t0
    nlist = idx.centroids.shape[0]

    t0 = time.perf_counter()
    want = [set(np.argsort(-(x @ q))[:10].tolist()) for q in queries]
    exact_ms = (time.perf_counter() - t0) / n_queries * 1000

    f32_mb = x.nbytes / 2**20
    i8_mb = idx.vectors.nbytes / 2**20
    print(f"\nn={n:,}  dim=768  nlist={nlist} (auto={_auto_nlist(n)})")
    print(f"  RAM: exact float32 {f32_mb:,.0f} MB → IVF int8 {i8_mb:,.0f} MB")
    print(f"  build: {build_s:.1f}s (one-time, persisted to ann-index.npz)")
    print(f"  exact scan: {exact_ms:.1f} ms/query")
    for nprobe in nprobes:
        t0 = time.perf_counter()
        rec, rec_rs = [], []
        for q, w in zip(queries, want):
            cand = idx.search(q, 26, nprobe=nprobe)
            got = {c for c, _ in cand[:10]}
            rec.append(len(got & w) / 10)
            # the shipping path (Store.vector_search) rescores candidates with
            # their float32 rows — here served from RAM; in production it is
            # ~26 SQLite PK lookups, <0.5 ms regardless of table size
            cids = [c for c, _ in cand]
            top = np.argsort(-(x[cids] @ q))[:10]
            rec_rs.append(len({cids[i] for i in top} & w) / 10)
        ms = (time.perf_counter() - t0) / n_queries * 1000
        print(f"  IVF nprobe={nprobe:>3} (scan ~{100 * nprobe / nlist:4.1f}%): "
              f"recall@10={np.mean(rec):.3f}  +rescore={np.mean(rec_rs):.3f}  "
              f"{ms:5.1f} ms/query  ({exact_ms / ms:4.1f}x faster)")


if __name__ == "__main__":
    sizes = [int(a.replace("k", "000").replace("M", "000000")) for a in sys.argv[1:]] \
        or [50_000, 200_000, 1_000_000]
    for n in sizes:
        run(n)
