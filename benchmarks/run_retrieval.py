"""Retrieval benchmark: Lemory hybrid vs ablations vs naive baselines.

Usage:
    python run_retrieval.py squad
    python run_retrieval.py multihop

Systems (all share the same index, embeddings and chunking — only the
retrieval strategy differs, which is exactly what separates KB products):
    lemory        full hybrid: vector + BM25 RRF + graph expansion + title boost
    lemory-nograph  ablation: fusion without graph expansion
    vector        naive RAG: pure cosine over the same embeddings
    bm25          classic lexical search
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (DATA, SYSTEMS, WORK, answer_in_text, full_support_metrics,
                    load_env, make_engine, prewarm_queries, rank_metrics, save_json)

K_EVAL = 8


def load_bench(name: str):
    if name == "squad":
        vault = WORK / "squad_vault"
        questions = json.loads((WORK / "squad_questions.json").read_text())
    elif name == "multihop":
        vault = DATA / "multihop" / "vault"
        questions = json.loads((DATA / "multihop" / "questions.json").read_text())
    else:
        raise SystemExit(f"unknown bench {name}")
    return vault, questions


def is_hit(bench: str, q: dict, hit) -> bool:
    if bench == "squad":
        return hit.title == q["article"] and answer_in_text(hit.text, q["answers"])
    # multihop: a hit is any gold note retrieved
    return hit.title in q["gold_notes"]


def main() -> None:
    load_env()
    bench = sys.argv[1] if len(sys.argv) > 1 else "multihop"
    vault, questions = load_bench(bench)

    eng = make_engine(vault, tag=bench)
    rep = eng.index()
    print(f"index: docs={eng.store.doc_count()} chunks={eng.store.chunk_count()} "
          f"links={eng.store.link_count()} embedded={rep.embedded} ({rep.seconds:.0f}s)")
    prewarm_queries(eng, [q["q"] for q in questions])

    results = {}
    for sysname, kw in SYSTEMS.items():
        t0 = time.time()
        flags_per_q: list[list[bool]] = []
        support: list[tuple[int, int]] = []
        by_hops: dict[int, list[tuple[int, int]]] = {1: [], 2: []}
        for q in questions:
            hits = eng.search(q["q"], k=K_EVAL, **kw)
            flags = [is_hit(bench, q, h) for h in hits]
            flags_per_q.append(flags)
            if bench == "multihop":
                found_titles = {h.title for h in hits if h.title in q["gold_notes"]}
                pair = (len(found_titles), len(q["gold_notes"]))
                support.append(pair)
                by_hops[q["hops"]].append(pair)
        dt = time.time() - t0
        m = rank_metrics(flags_per_q)
        if bench == "multihop":
            m.update(full_support_metrics(support, "@8"))
            for hops, arr in by_hops.items():
                if arr:
                    m[f"full_support@8_hops{hops}"] = full_support_metrics(arr)["full_support"]
        m["ms_per_query"] = 1000 * dt / len(questions)
        results[sysname] = m
        print(f"{sysname:16s} " + " ".join(f"{k}={v:.3f}" for k, v in m.items()))

    save_json(WORK / f"results_retrieval_{bench}.json", results)
    print(f"saved -> {WORK}/results_retrieval_{bench}.json")


if __name__ == "__main__":
    main()
