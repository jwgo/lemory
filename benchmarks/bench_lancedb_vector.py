"""LanceDB ANN vs Lemory IVF-int8 on the same real-embedding manifold (200k×768).

Same corpus/queries as bench_scale.py: real gemini-embedding-001 vectors
scaled up by nearest-neighbor SLERP. recall@10 vs the exact float32 scan.
"""

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bench_scale import blocks, load_real_vectors, scale_up  # noqa: E402
from lemory.storage.ann import IVFFlatIndex  # noqa: E402

WORK = Path(__file__).resolve().parent / "work" / "storage-alt" / "lance-vec"
N = 200_000


def main() -> None:
    import lancedb

    base = load_real_vectors()
    x = scale_up(base, N)
    ids = np.arange(N, dtype=np.int64)
    rng = np.random.default_rng(42)
    qi = rng.permutation(len(base))[:40]
    queries = base[qi] + 0.05 * rng.standard_normal((40, 768)).astype(np.float32)
    queries /= np.linalg.norm(queries, axis=1, keepdims=True)
    want = [set(np.argsort(-(x @ q))[:10].tolist()) for q in queries]

    # ---- lemory IVF-int8 (shipping path incl. float32 rescore)
    t0 = time.perf_counter()
    idx = IVFFlatIndex.build(blocks(x, ids), total=N, dim=768)
    t_build = time.perf_counter() - t0
    t0 = time.perf_counter()
    rec = []
    for q, w in zip(queries, want):
        cand = [c for c, _ in idx.search(q, 26, nprobe=48)]
        top = np.argsort(-(x[cand] @ q))[:10]
        rec.append(len({cand[i] for i in top} & w) / 10)
    ms = (time.perf_counter() - t0) / len(queries) * 1000
    print(f"lemory ivf-int8   build={t_build:6.1f}s  query={ms:6.2f}ms  "
          f"recall@10={np.mean(rec):.3f}  ram={idx.vectors.nbytes / 2**20:.0f}MB")

    # ---- lancedb IVF-PQ (its default ANN index)
    shutil.rmtree(WORK, ignore_errors=True)
    db = lancedb.connect(str(WORK))
    t0 = time.perf_counter()
    tbl = db.create_table(
        "vecs", [{"id": int(i), "vector": x[i]} for i in range(N)])
    tbl.create_index(metric="cosine", num_partitions=256, num_sub_vectors=96)
    t_build = time.perf_counter() - t0
    for nprobes, refine in ((20, None), (20, 10), (50, 10)):
        t0 = time.perf_counter()
        rec = []
        for q, w in zip(queries, want):
            s = tbl.search(q).metric("cosine").nprobes(nprobes)
            if refine:
                s = s.refine_factor(refine)
            got = {r["id"] for r in s.limit(10).to_list()}
            rec.append(len(got & w) / 10)
        ms = (time.perf_counter() - t0) / len(queries) * 1000
        disk = sum(f.stat().st_size for f in WORK.rglob("*") if f.is_file()) / 2**20
        print(f"lancedb ivf-pq    build={t_build:6.1f}s  query={ms:6.2f}ms  "
              f"recall@10={np.mean(rec):.3f}  disk={disk:.0f}MB  "
              f"(nprobes={nprobes} refine={refine})")


if __name__ == "__main__":
    main()
