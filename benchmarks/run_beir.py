"""BEIR retrieval benchmark on Lemory, keyless (e5-small-ko-v2 + BM25 + graph).

The metric that matters for RAG: does the gold document land in the top-k
(Recall), and how well is it ranked (NDCG@10, BEIR's standard). Compares
Lemory's hybrid fusion to its own dense-only and BM25-only legs, and you read
those against published BEIR baselines (BM25 ~0.66 / e5-small ~0.68 NDCG@10 on
SciFact).

    python benchmarks/run_beir.py scifact          # or nfcorpus, arguana, scidocs, fiqa, ...

Loads the corpus/queries/qrels straight from the HF `BeIR/<name>` datasets, no
API key. Writes each doc as one note (id = filename) and evaluates note-level.
"""
from __future__ import annotations

import math
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("GOOGLE_API_KEY", None)
sys.path.insert(0, str(Path(__file__).parent))
from common import WORK  # noqa: E402
from lemory.config import LemoryConfig  # noqa: E402
from lemory.engine import Engine  # noqa: E402
from lemory.retrieval.search import hybrid_search  # noqa: E402

import warnings  # noqa: E402
warnings.filterwarnings("ignore")


def load(name: str):
    from datasets import load_dataset
    corpus = {str(d["_id"]): d for d in load_dataset(f"BeIR/{name}", "corpus", split="corpus")}
    queries = {str(q["_id"]): q["text"] for q in load_dataset(f"BeIR/{name}", "queries", split="queries")}
    qrels: dict[str, dict[str, int]] = defaultdict(dict)
    split = "test"
    for r in load_dataset(f"BeIR/{name}-qrels", split=split):
        if int(r["score"]) > 0:
            qrels[str(r["query-id"])][str(r["corpus-id"])] = int(r["score"])
    return corpus, queries, qrels


def build_vault(name: str, corpus: dict) -> Path:
    vault = WORK / f"beir-{name}" / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    if len(list(vault.glob("*.md"))) != len(corpus):
        for f in vault.glob("*.md"):
            f.unlink()
        for _id, d in corpus.items():
            title = (d.get("title") or "").strip()
            body = d.get("text") or ""
            (vault / f"{_id}.md").write_text((f"# {title}\n\n{body}") if title else body,
                                             encoding="utf-8")
    return vault


def ndcg_at(ranked_ids: list[str], gold: dict[str, int], k: int) -> float:
    dcg = 0.0
    for i, did in enumerate(ranked_ids[:k]):
        rel = gold.get(did, 0)
        if rel:
            dcg += (2 ** rel - 1) / math.log2(i + 2)
    ideal = sorted(gold.values(), reverse=True)[:k]
    idcg = sum((2 ** rel - 1) / math.log2(i + 2) for i, rel in enumerate(ideal))
    return dcg / idcg if idcg else 0.0


def evaluate(eng, queries, qrels, mode, graph, ks=(10, 100)):
    qids = [q for q in qrels if q in queries]
    rec = {k: 0.0 for k in ks}
    ndcg10 = 0.0
    lat = []
    for qid in qids:
        t = time.time()
        res = hybrid_search(eng, queries[qid], k=max(ks), mode=mode, graph=graph)
        lat.append((time.time() - t) * 1000)
        ranked = []
        for h in res.hits:  # dedup to unique doc ids, keep rank order
            did = Path(h.path).stem
            if did not in ranked:
                ranked.append(did)
        gold = qrels[qid]
        ng = len(gold)
        for k in ks:
            hit = len(set(ranked[:k]) & set(gold))
            rec[k] += hit / ng
        ndcg10 += ndcg_at(ranked, gold, 10)
    n = len(qids)
    lat.sort()
    return {"n_q": n, "ndcg@10": round(ndcg10 / n, 4),
            **{f"recall@{k}": round(rec[k] / n, 4) for k in ks},
            "p50_ms": round(lat[len(lat) // 2], 1)}


def main(name: str):
    corpus, queries, qrels = load(name)
    print(f"[BEIR {name}] corpus={len(corpus)} queries(test)={len([q for q in qrels if q in queries])}", flush=True)
    vault = build_vault(name, corpus)
    cfg = LemoryConfig(vault=vault, data_dir=WORK / f"beir-{name}" / "idx",
                       provider="local", local_embed_backend="fastembed")
    eng = Engine(cfg)
    t0 = time.time()
    rep = eng.index()
    print(f"indexed {eng.store.doc_count()} docs / {rep.chunks} chunks in {time.time()-t0:.0f}s "
          f"({eng.cfg.active_embed_model()})", flush=True)
    for label, (mode, graph) in [("hybrid+graph", ("hybrid", True)),
                                 ("hybrid", ("hybrid", False)),
                                 ("dense (e5-ko)", ("vector", False)),
                                 ("bm25", ("bm25", False))]:
        s = evaluate(eng, queries, qrels, mode, graph)
        print(f"  {label:16s} NDCG@10={s['ndcg@10']:.4f}  R@10={s['recall@10']:.4f}  "
              f"R@100={s['recall@100']:.4f}  p50={s['p50_ms']}ms  (n={s['n_q']})", flush=True)
    print(f"BEIR_{name}_DONE", flush=True)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "scifact")
