"""Second-brain scale verification: index the ~1,200-note mixed vault and
verify planted facts are retrievable, sync is incremental, and latency holds.

LLM-free by design (deterministic local embedder), so it runs anywhere and
measures everything except semantic embedding quality — which the multihop/
maple/law/SQuAD benches cover on real embeddings.

    python gen_secondbrain.py && python run_secondbrain.py
"""

from __future__ import annotations

import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import json

from common import WORK, save_json

from lemory.config import LemoryConfig
from lemory.engine import Engine

sys.path.insert(0, str(Path(__file__).parent.parent / "tests"))
from conftest import DIM, FakeGemini  # deterministic bag-of-words embedder

OUT = WORK / "secondbrain"


def main() -> None:
    vault = OUT / "vault"
    planted = json.loads((OUT / "planted.json").read_text())
    data_dir = OUT / "index"

    cfg = LemoryConfig(vault=vault, data_dir=data_dir, embed_dim=DIM, gemini_api_key="x")
    eng = Engine(cfg, llm=FakeGemini())

    t0 = time.time()
    rep = eng.index()
    t_full = time.time() - t0
    print(f"full index: {eng.store.doc_count()} docs / {eng.store.chunk_count()} chunks / "
          f"{eng.store.link_count()} links in {t_full:.1f}s")

    # incremental: touch one note
    some = next(vault.glob("일지/*.md"))
    some.write_text(some.read_text() + "\n추가 메모.\n", encoding="utf-8")
    t0 = time.time()
    rep2 = eng.index()
    t_incr = time.time() - t0
    assert rep2.updated == 1 and rep2.added == 0, rep2
    print(f"incremental sync (1 edited note): {t_incr:.2f}s")

    # planted-fact retrieval (BM25 leg carries exact tokens; hybrid must find)
    rng = random.Random(3)
    results = {}
    for mode in ("hybrid", "bm25"):
        hit1 = hit5 = 0
        t0 = time.time()
        for p in planted:
            hits = eng.search(p["q"], k=5, mode=mode)
            titles = [h.title for h in hits]
            if titles[:1] == [p["gold_note"]]:
                hit1 += 1
            if p["gold_note"] in titles:
                hit5 += 1
        dt = 1000 * (time.time() - t0) / len(planted)
        results[mode] = {"hit@1": hit1 / len(planted), "hit@5": hit5 / len(planted),
                         "ms_per_query": dt}
        print(f"{mode:8s} planted-fact hit@1={hit1/len(planted):.3f} "
              f"hit@5={hit5/len(planted):.3f} ({dt:.1f} ms/q)")

    # graph sanity: project notes must link to their owner (wikilink)
    docs = {d.title: d.id for d in eng.store.all_docs()}
    sample_projects = [t for t in docs if "-" in t and not t.startswith(("회의", "클리핑", "맛집"))]
    linked = 0
    checked = 0
    for t in rng.sample(sample_projects, min(30, len(sample_projects))):
        nbrs = eng.store.neighbors([docs[t]])[docs[t]]
        checked += 1
        if any(k == "wiki" for _, k, _ in nbrs):
            linked += 1
    print(f"graph: {linked}/{checked} sampled project notes have wiki edges")

    out = {
        "docs": eng.store.doc_count(), "chunks": eng.store.chunk_count(),
        "links": eng.store.link_count(), "full_index_s": t_full,
        "incremental_sync_s": t_incr, "planted": results,
        "graph_linked_ratio": linked / max(checked, 1),
    }
    save_json(WORK / "results_secondbrain.json", out)
    print(f"saved -> {WORK}/results_secondbrain.json")

    assert results["hybrid"]["hit@5"] >= 0.95, "planted facts must be retrievable"
    assert t_incr < 30, "incremental sync too slow"


if __name__ == "__main__":
    main()
