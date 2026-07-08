"""Local performance benchmark: retrieval latency vs index size.

No network needed — vectors are synthetic. Measures the full hybrid pipeline
(vector + BM25 + RRF + graph expansion) at personal-vault scales, which is the
latency a user feels after the (network-bound) query embedding.
"""

from __future__ import annotations

import random
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from common import WORK, save_json

from lemory.config import LemoryConfig
from lemory.engine import Engine
from lemory.retrieval.search import hybrid_search
from lemory.storage import Store

DIM = 768
# realistic Zipfian vocabulary (~6k words) so BM25 posting lists behave like
# real text instead of a degenerate every-chunk-matches corpus
_rng = random.Random(7)
_SYLL = ["ka", "ro", "min", "ta", "vel", "sor", "ne", "qui", "lu", "bar",
         "chi", "den", "fo", "gra", "hel", "is", "jor", "kel", "mo", "pra"]
VOCAB = ["".join(_rng.choices(_SYLL, k=_rng.randint(2, 4))) for _ in range(6000)]
_WEIGHTS = [1.0 / (i + 1) for i in range(len(VOCAB))]  # Zipf


def sample_words(rng: random.Random, k: int) -> list[str]:
    return rng.choices(VOCAB, weights=_WEIGHTS, k=k)


class NullLLM:
    def embed(self, texts, task_type=""):
        rng = np.random.default_rng(0)
        v = rng.standard_normal((len(texts), DIM)).astype(np.float32)
        return v / np.linalg.norm(v, axis=1, keepdims=True)

    def close(self):
        pass


def build(n_chunks: int, tmp: Path) -> Engine:
    rng = random.Random(42)
    nrng = np.random.default_rng(42)
    db = tmp / f"perf_{n_chunks}.db"
    if db.exists():
        db.unlink()
    store = Store(db)
    cfg = LemoryConfig(vault=tmp, data_dir=tmp, embed_dim=DIM, gemini_api_key="x")
    eng = Engine(cfg, llm=NullLLM(), store=store)

    chunks_per_doc = 6
    n_docs = n_chunks // chunks_per_doc
    t0 = time.time()
    doc_ids = []
    for d in range(n_docs):
        w = sample_words(rng, 2)
        title = f"{w[0].title()} {w[1].title()} {d}"
        texts = [("", " ".join(sample_words(rng, 120))) for _ in range(chunks_per_doc)]
        vecs = nrng.standard_normal((chunks_per_doc, DIM)).astype(np.float32)
        vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
        doc_id = store.upsert_document(f"n{d}.md", title, f"h{d}", 0.0, [], {}, 0.0)
        store.replace_chunks(doc_id, title, texts, vecs)
        doc_ids.append(doc_id)
    # realistic link density: ~4 links per note
    for d in doc_ids:
        edges = [(rng.choice(doc_ids), "wiki", 1.0) for _ in range(4)]
        store.replace_links(d, [(dst, k, w) for dst, k, w in edges if dst != d])
    build_s = time.time() - t0
    print(f"  built {store.doc_count()} docs / {store.chunk_count()} chunks in {build_s:.1f}s")
    return eng


def bench(eng: Engine, n_queries: int = 50) -> dict:
    rng = random.Random(1)
    queries = [" ".join(sample_words(rng, 5)) for _ in range(n_queries)]
    # warm the matrix
    eng.store.vector_search(np.zeros(DIM, dtype=np.float32), 1)
    out = {}
    for mode, kw in {
        "hybrid+graph": dict(mode="hybrid", graph=True),
        "hybrid": dict(mode="hybrid", graph=False),
        "vector": dict(mode="vector", graph=False),
        "bm25": dict(mode="bm25", graph=False),
    }.items():
        t0 = time.perf_counter()
        for q in queries:
            hybrid_search(eng, q, k=8, **kw)
        out[mode] = 1000 * (time.perf_counter() - t0) / n_queries
    return out


def main() -> None:
    tmp = WORK / "perf"
    tmp.mkdir(parents=True, exist_ok=True)
    results = {}
    for n in (2_000, 10_000, 50_000):
        print(f"n_chunks={n}")
        eng = build(n, tmp)
        results[str(n)] = bench(eng)
        print("  " + " ".join(f"{k}={v:.2f}ms" for k, v in results[str(n)].items()))
        eng.store.close()
    save_json(WORK / "results_perf.json", results)
    print(f"saved -> {WORK}/results_perf.json")


if __name__ == "__main__":
    main()
