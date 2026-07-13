"""Re-measure the Smart-Connections *class* row (its default bge-micro-v2,
pure cosine, no graph) on the v2 KorMapleQA question set. Local-only."""
from __future__ import annotations

import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

os.environ.pop("GOOGLE_API_KEY", None)
os.environ.pop("GEMINI_API_KEY", None)

sys.path.insert(0, str(Path(__file__).parent))
from common import DATA, WORK, make_engine, prewarm_queries  # noqa: E402
from lemory.retrieval.search import hybrid_search  # noqa: E402

QFILE = DATA / "kormapleqa" / "questions.jsonl"
VAULT = DATA / "maple_real" / "vault"


def main():
    from fastembed import TextEmbedding
    from fastembed.common.model_description import ModelSource, PoolingType
    try:
        TextEmbedding.add_custom_model(
            model="TaylorAI/bge-micro-v2", pooling=PoolingType.CLS,
            normalization=True,
            sources=ModelSource(hf="TaylorAI/bge-micro-v2"), dim=384)
    except Exception:
        pass

    questions = [json.loads(l) for l in QFILE.read_text().splitlines()]
    eng = make_engine(VAULT, tag="kormapleqa-sc",
                      local_embed_model="TaylorAI/bge-micro-v2")
    rep = eng.index()
    print(f"index: docs={eng.store.doc_count()} chunks={eng.store.chunk_count()} "
          f"embedded={rep.embedded} model={eng.cfg.active_embed_model()}", flush=True)
    prewarm_queries(eng, [q["q"] for q in questions])

    per_type = defaultdict(list)
    lat = []
    for q in questions:
        if not q.get("answerable", True):
            continue
        t0 = time.time()
        res = hybrid_search(eng, q["q"], k=8, mode="vector", graph=False)
        lat.append(time.time() - t0)
        titles = [h.title for h in res.hits]
        golds = q["gold_notes"]
        dr = next((i for i, t in enumerate(titles) if t in golds), None)
        per_type[q["type"]].append({"doc1": dr == 0, "doc8": dr is not None})
    allrows = [r for rows in per_type.values() for r in rows]
    def agg(rows):
        n = len(rows)
        return {"n": n, "doc1": round(sum(r["doc1"] for r in rows)/n, 4),
                "doc8": round(sum(r["doc8"] for r in rows)/n, 4)}
    out = {"all": agg(allrows), **{t: agg(r) for t, r in per_type.items()}}
    lat.sort()
    out["p50_ms"] = round(lat[len(lat)//2]*1000, 2)
    print("smartconn-class all:", out["all"], f"p50={out['p50_ms']}ms")
    (WORK / "remeasure_smartconn.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
