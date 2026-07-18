"""Ablation: is the post-0.904 recency change what dropped LongMemEval temporal?

Reruns ONLY the temporal-reasoning questions with recency_boost=0 and compares
per-question against the completed full-run rows (default config). If strict@5
recovers toward the pre-change 0.835, the vague-recency anchoring (dd25d9c) is
the regression source on this benchmark; if not, the delta is dataset-copy or
elsewhere.

    python benchmarks/ablate_lme_recency.py
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from common import WORK  # noqa: E402
from run_longmemeval import DATA_FILE, build_vault  # noqa: E402
from run_longmemeval_full import note_for_session  # noqa: E402

from lemory.config import LemoryConfig  # noqa: E402
from lemory.engine import Engine  # noqa: E402

OUT = WORK / "longmemeval-full"
ABL = OUT / "ablation_recency0.jsonl"


def main() -> None:
    questions = json.loads(DATA_FILE.read_text())
    questions = [q for q in questions
                 if q["question_type"] == "temporal-reasoning"
                 and not str(q["question_id"]).endswith("_abs")]
    done = set()
    if ABL.exists():
        done = {json.loads(x)["qid"] for x in ABL.read_text().splitlines() if x.strip()}
    t0 = time.time()
    for qi, q in enumerate(questions):
        qid = str(q["question_id"])
        if qid in done:
            continue
        vault = build_vault(q)
        data_dir = OUT / "abl-idx" / qid
        cfg = LemoryConfig(vault=vault, data_dir=data_dir, provider="local",
                           recency_boost=0.0)
        eng = Engine(cfg)
        try:
            eng.index()
            gold = {note_for_session(q, s) for s in q["answer_session_ids"]}
            gold.discard(None)
            hits = eng.search(q["question"], k=10, mode="hybrid", graph=True)
            seen: list[str] = []
            for h in hits:
                if h.path not in seen:
                    seen.append(h.path)
            row = {"qid": qid, "n_gold": len(gold),
                   "all@5": bool(gold) and gold <= set(seen[:5]),
                   "any@5": bool(gold & set(seen[:5]))}
        finally:
            eng.close()
            shutil.rmtree(data_dir, ignore_errors=True)
        with open(ABL, "a") as fh:
            fh.write(json.dumps(row) + "\n")
        if (qi + 1) % 20 == 0:
            print(f"{qi+1}/{len(questions)} ({(time.time()-t0)/60:.0f} min)", flush=True)

    rows = [json.loads(x) for x in ABL.read_text().splitlines() if x.strip()]
    rows = [r for r in rows if r["n_gold"] > 0]
    strict = sum(r["all@5"] for r in rows) / len(rows)
    anyk = sum(r["any@5"] for r in rows) / len(rows)
    print(f"temporal-reasoning, recency_boost=0: strict@5={strict:.3f} any@5={anyk:.3f} (n={len(rows)})")
    print("default-config same questions (from full run): strict@5=0.740 any@5=0.953")


if __name__ == "__main__":
    main()
