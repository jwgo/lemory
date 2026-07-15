"""Extreme-mode BEIR: does the local Qwen3-Reranker recover the fusion loss?

run_beir.py showed hybrid RRF fusion slightly demotes the gold on dense-dominant
datasets (ArguAna: hybrid 0.321 < dense 0.402) — the gold is retrieved
(R@100=0.979) but ranked out of the top-10 by the lexical leg. A cross-encoder
reorder of the fused top-N is the standard, Korean-safe fix (it never touches
the fusion weights the Korean corpora depend on). This measures that lift.

    python benchmarks/run_beir_rerank.py arguana 300   # dataset, optional query cap

Reuses the index run_beir.py already built. The reranker is CPU-heavy
(one llama.cpp forward pass per candidate), so a query cap subsets the test
set — the cap is printed, never silent.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("GOOGLE_API_KEY", None)
sys.path.insert(0, str(Path(__file__).parent))
import warnings  # noqa: E402

warnings.filterwarnings("ignore")

from common import WORK  # noqa: E402
from lemory.config import LemoryConfig  # noqa: E402
from lemory.engine import Engine  # noqa: E402
from run_beir import build_vault, evaluate, load  # noqa: E402

RERANK_TOP = 50  # deep enough to reach a gold the lexical fusion demoted below 10


def main(name: str, max_q: int | None) -> None:
    corpus, queries, qrels = load(name)
    test_qids = sorted(q for q in qrels if q in queries)
    if max_q and len(test_qids) > max_q:
        sub = set(test_qids[:max_q])
        qrels = {q: g for q, g in qrels.items() if q in sub}
        print(f"[BEIR {name}] SUBSET n={max_q} of {len(test_qids)} test queries "
              f"(reranker is CPU-bound)", flush=True)
    else:
        print(f"[BEIR {name}] full n={len(test_qids)} test queries", flush=True)

    vault = build_vault(name, corpus)
    cfg = LemoryConfig(vault=vault, data_dir=WORK / f"beir-{name}" / "idx",
                       provider="local", local_embed_backend="fastembed",
                       rerank_top=RERANK_TOP)
    eng = Engine(cfg)
    t0 = time.time()
    rep = eng.index()
    print(f"indexed {eng.store.doc_count()} docs / {rep.chunks} chunks in "
          f"{time.time()-t0:.0f}s ({eng.cfg.active_embed_model()})", flush=True)

    for label, reranker_on in [("hybrid (fusion only)", False),
                               (f"hybrid + Qwen3-Reranker(top{RERANK_TOP})", True)]:
        eng.cfg.reranker = reranker_on
        s = evaluate(eng, queries, qrels, "hybrid", graph=False)
        print(f"  {label:38s} NDCG@10={s['ndcg@10']:.4f}  R@10={s['recall@10']:.4f}  "
              f"R@100={s['recall@100']:.4f}  p50={s['p50_ms']}ms  (n={s['n_q']})",
              flush=True)
    print(f"BEIR_RERANK_{name}_DONE", flush=True)


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "arguana"
    cap = int(sys.argv[2]) if len(sys.argv) > 2 else None
    main(name, cap)
