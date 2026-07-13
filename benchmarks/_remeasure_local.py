"""Re-measure the zero-key rows (local hybrid + dense-vector-only) on the
v2 (diversified-phrasing) KorMapleQA question set. Forces the local fastembed
embedder by clearing the Gemini key, so it never touches the (depleted) API."""
from __future__ import annotations

import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

# strip any inherited Gemini key BEFORE importing config → forces local embedder
os.environ.pop("GOOGLE_API_KEY", None)
os.environ.pop("GEMINI_API_KEY", None)

sys.path.insert(0, str(Path(__file__).parent))
from common import DATA, WORK, make_engine, normalize_ko, prewarm_queries  # noqa: E402
from lemory.retrieval.search import hybrid_search  # noqa: E402

QFILE = DATA / "kormapleqa" / "questions.jsonl"
VAULT = DATA / "maple_real" / "vault"
K = 8


def evaluate(eng, questions, mode, graph):
    per_type = defaultdict(list)
    latencies = []
    for q in questions:
        if not q.get("answerable", True):
            continue
        t0 = time.time()
        res = hybrid_search(eng, q["q"], k=K, mode=mode, graph=graph)
        latencies.append(time.time() - t0)
        titles = [h.title for h in res.hits]
        golds = q["gold_notes"]
        doc_rank = next((i for i, t in enumerate(titles) if t in golds), None)
        row = {"doc1": doc_rank == 0, "doc8": doc_rank is not None}
        if q["type"] == "twohop":
            row["fs"] = set(golds) <= set(titles)
        per_type[q["type"]].append(row)
    out = {}
    allrows = [r for rows in per_type.values() for r in rows]
    for label, rows in [("all", allrows)] + sorted(per_type.items()):
        n = len(rows)
        out[label] = {"n": n,
                      "doc1": round(sum(r["doc1"] for r in rows) / n, 4),
                      "doc8": round(sum(r["doc8"] for r in rows) / n, 4)}
        fs = [r for r in rows if "fs" in r]
        if fs:
            out[label]["fs"] = round(sum(r["fs"] for r in fs) / len(fs), 4)
    latencies.sort()
    out["p50_ms"] = round(latencies[len(latencies) // 2] * 1000, 2)
    return out


def main():
    questions = [json.loads(l) for l in QFILE.read_text().splitlines()]
    eng = make_engine(VAULT, tag="maple_real-local")
    rep = eng.index()
    print(f"index: docs={eng.store.doc_count()} chunks={eng.store.chunk_count()} "
          f"embedded={rep.embedded} model={eng.cfg.active_embed_model()}", flush=True)
    prewarm_queries(eng, [q["q"] for q in questions])
    for name, (mode, graph) in [("hybrid-local", ("hybrid", True)),
                                ("vector-only", ("vector", False))]:
        s = evaluate(eng, questions, mode, graph)
        print(f"\n=== {name} ===")
        print(f"  all      doc1={s['all']['doc1']} doc8={s['all']['doc8']} p50={s['p50_ms']}ms")
        for t in ("single", "masked", "twohop", "temporal", "kw", "casual", "typo"):
            if t in s:
                fs = f" fs={s[t].get('fs')}" if "fs" in s[t] else ""
                print(f"  {t:9s} doc1={s[t]['doc1']} doc8={s[t]['doc8']}{fs}")
        (WORK / f"remeasure_{name}.json").write_text(json.dumps(s, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
