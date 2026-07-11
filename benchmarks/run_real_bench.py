"""Real-vault benchmark: retrieval quality on real public Obsidian vaults
(kepano personal vault; obsidian-help docs vault) with code-verified QA.

Evaluates the standard SYSTEMS plus this round's two adoptions as explicit
arms, so gains are attributable:

  lemory            hybrid + graph (current defaults)
  lemory+hops2      graph_hops=2 (HippoRAG-style propagation)
  lemory-plain      stub_enrichment disabled at index time (ablation)
  vector / bm25     naive baselines (on the enriched index)

    python run_real_bench.py kepano
    python run_real_bench.py help     # run prep_help.py first
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (DATA, WORK, full_support_metrics, load_env, make_engine,
                    prewarm_queries, rank_metrics, save_json)

K = 8


def evaluate(eng, questions, **search_kw):
    flags, support = [], []
    by_hops: dict[int, list[tuple[int, int]]] = {1: [], 2: []}
    t0 = time.time()
    for q in questions:
        hits = eng.search(q["q"], k=K, **search_kw)
        titles = {h.title for h in hits}
        gold = set(q["gold_notes"])
        flags.append([h.title in gold for h in hits])
        pair = (len(titles & gold), len(gold))
        support.append(pair)
        by_hops[q["hops"]].append(pair)
    m = rank_metrics(flags)
    m.update(full_support_metrics(support, "@8"))
    for hops, arr in by_hops.items():
        if arr:
            m[f"full_support@8_hops{hops}"] = full_support_metrics(arr)["full_support"]
    m["ms_per_query"] = 1000 * (time.time() - t0) / len(questions)
    return m


def main() -> None:
    load_env()
    bench = sys.argv[1] if len(sys.argv) > 1 else "kepano"
    vault = (DATA / "kepano" / "vault") if bench == "kepano" else (WORK / "help_vault")
    questions = json.loads((DATA / bench / "questions.json").read_text())
    print(f"{bench}: {len(questions)} questions "
          f"({len([q for q in questions if q['hops'] == 2])} 2-hop)")

    results = {}

    # enriched index (product defaults)
    eng = make_engine(vault, tag=f"{bench}-enriched")
    rep = eng.index()
    print(f"enriched index: docs={eng.store.doc_count()} chunks={eng.store.chunk_count()} "
          f"links={eng.store.link_count()} (+{rep.embedded} embeds)")
    prewarm_queries(eng, [q["q"] for q in questions])
    results["lemory"] = evaluate(eng, questions, mode="hybrid", graph=True)
    eng.cfg.graph_hops = 2
    results["lemory+hops2"] = evaluate(eng, questions, mode="hybrid", graph=True)
    eng.cfg.graph_hops = 1
    results["vector"] = evaluate(eng, questions, mode="vector", graph=False)
    results["bm25"] = evaluate(eng, questions, mode="bm25", graph=False)
    eng.store.close()

    # ablation: no stub enrichment
    plain = make_engine(vault, tag=f"{bench}-plain", stub_enrichment=False)
    plain.index()
    prewarm_queries(plain, [q["q"] for q in questions])
    results["lemory-plain"] = evaluate(plain, questions, mode="hybrid", graph=True)
    plain.cfg.graph_hops = 2
    results["lemory-plain+hops2"] = evaluate(plain, questions, mode="hybrid", graph=True)
    plain.store.close()

    for name, m in results.items():
        print(f"{name:20s} " + " ".join(f"{k}={v:.3f}" for k, v in m.items()))
    save_json(WORK / f"results_real_{bench}.json", results)
    print(f"saved -> {WORK}/results_real_{bench}.json")


if __name__ == "__main__":
    main()
