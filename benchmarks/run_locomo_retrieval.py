"""LOCOMO retrieval — evidence recall, zero API calls.

The judge-graded LOCOMO table (§7) needs a Gemini generator+judge; this is
the retrieval-only axis on the same 160-question stratified sample: what
fraction of a question's gold evidence TURNS appear verbatim in the retrieved
context (evidence-recall, run_locomo's ev_found/ev_total — no LLM anywhere).
Runs on the keyless local default (e5-small-ko-v2), reproducible on a laptop:

    python benchmarks/prep_locomo.py          # once: download + build vaults
    python benchmarks/run_locomo_retrieval.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("GOOGLE_API_KEY", None)
sys.path.insert(0, str(Path(__file__).parent))
from common import SYSTEMS, WORK, save_json  # noqa: E402
from prep_locomo import OUT  # noqa: E402
from run_locomo import turn_texts  # noqa: E402

from lemory.config import LemoryConfig  # noqa: E402
from lemory.engine import Engine  # noqa: E402
from lemory.retrieval.intent import adaptive_k  # noqa: E402

K = 10


def main() -> None:
    eval_set = json.loads((OUT / "eval_set.json").read_text())
    engines: dict[int, Engine] = {}

    def engine_for(conv: int) -> Engine:
        if conv not in engines:
            cfg = LemoryConfig(vault=OUT / "vaults" / f"conv{conv}",
                               data_dir=WORK / f"index-locomo-e5-{conv}",
                               provider="local", local_embed_backend="fastembed")
            engines[conv] = Engine(cfg)
            rep = engines[conv].index()
            if rep.embedded:
                print(f"  conv{conv}: {rep.chunks} chunks ({rep.embedded} embedded)",
                      flush=True)
        return engines[conv]

    results = {}
    for sys_name, opts in SYSTEMS.items():
        rows = []
        by_cat: dict[int, list[float]] = defaultdict(list)
        lat = []
        for q in eval_set:
            eng = engine_for(q["conv"])
            ev_texts = turn_texts(q["conv"], q["evidence"])
            if not ev_texts:
                continue
            k_eff = adaptive_k(q["q"], K)
            t0 = time.time()
            hits = eng.search(q["q"], k=k_eff, **opts)
            lat.append(time.time() - t0)
            joined = " ".join(h.text for h in hits).lower()
            found = sum(1 for t in ev_texts if t.lower() in joined)
            r = found / len(ev_texts)
            rows.append(r)
            by_cat[q["category"]].append(r)
        lat.sort()
        results[sys_name] = {
            "n": len(rows),
            "evidence_recall@10": round(sum(rows) / len(rows), 4),
            **{f"cat{c}_recall": round(sum(v) / len(v), 4)
               for c, v in sorted(by_cat.items())},
            "p50_ms": round(lat[len(lat) // 2] * 1000, 1),
        }
        print(sys_name, results[sys_name], flush=True)
    save_json(WORK / "results_locomo_retrieval.json", results)
    print("LOCOMO_RETRIEVAL_DONE", flush=True)


if __name__ == "__main__":
    main()
