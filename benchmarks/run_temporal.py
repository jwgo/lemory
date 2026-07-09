"""Run the temporal scenario benchmark.

Metric per query: does the top-1 result contain the CURRENT answer (and, for
evolving facts, does the top-1 avoid the superseded value)? Plus answer-in-
top-3. Systems: Lemory (recency on) vs Lemory recency-off vs vector vs bm25.

    python benchmarks/gen_temporal.py
    python benchmarks/run_temporal.py          # real Gemini embeddings (headline)
    python benchmarks/run_temporal.py --fake   # deterministic local embedder (CI smoke)
"""

from __future__ import annotations

import sys
import json
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "tests"))
from common import WORK, save_json
from conftest import DIM, FakeGemini

from gen_temporal import TODAY
from lemory.config import LemoryConfig
from lemory.engine import Engine

OUT = WORK / "temporal"
NOW = datetime(TODAY.year, TODAY.month, TODAY.day, 18).timestamp()

SYSTEMS = {
    "lemory": dict(mode="hybrid", graph=True),
    "lemory-norecency": dict(mode="hybrid", graph=True),
    "vector": dict(mode="vector", graph=False),
    "bm25": dict(mode="bm25", graph=False),
}


def top_contains(hits, text: str, n: int) -> bool:
    return any(text.lower() in (h.text + " " + h.title).lower() for h in hits[:n])


def main(fake: bool = False) -> None:
    queries = json.loads((OUT / "queries.json").read_text())
    if not fake:
        from common import load_env
        load_env()
    results = {}
    for name, opts in SYSTEMS.items():
        common_cfg = dict(
            recency_boost=0.0 if name == "lemory-norecency" else 1.0,
        )
        if fake:
            cfg = LemoryConfig(vault=OUT / "vault", data_dir=WORK / "index-temporal",
                               embed_dim=DIM, gemini_api_key="x", **common_cfg)
            eng = Engine(cfg, llm=FakeGemini())
        else:
            cfg = LemoryConfig(vault=OUT / "vault", data_dir=WORK / "index-temporal-real",
                               **common_cfg)
            eng = Engine(cfg)
        eng.now = lambda: NOW
        eng.index()

        per_kind: dict[str, list[dict]] = {}
        latencies = []
        for q in queries:
            t = time.time()
            hits = eng.search(q["q"], k=8, mode=opts["mode"], graph=opts["graph"])
            latencies.append(time.time() - t)
            correct1 = top_contains(hits, q["answer"], 1)
            correct3 = top_contains(hits, q["answer"], 3)
            trapped = bool(q.get("wrong_answer")) and top_contains(hits, q["wrong_answer"], 1) and not correct1
            per_kind.setdefault(q["kind"], []).append(
                {"hit1": correct1, "hit3": correct3, "trapped": trapped})
        summary = {}
        for kind, rows in per_kind.items():
            summary[f"{kind}_hit@1"] = sum(r["hit1"] for r in rows) / len(rows)
            summary[f"{kind}_hit@3"] = sum(r["hit3"] for r in rows) / len(rows)
            if any(r["trapped"] for r in rows):
                summary[f"{kind}_trapped@1"] = sum(r["trapped"] for r in rows) / len(rows)
        all_rows = [r for rows in per_kind.values() for r in rows]
        summary["overall_hit@1"] = sum(r["hit1"] for r in all_rows) / len(all_rows)
        summary["overall_hit@3"] = sum(r["hit3"] for r in all_rows) / len(all_rows)
        summary["ms_per_query"] = sorted(latencies)[len(latencies) // 2] * 1000
        results[name] = summary
        pretty = "  ".join(f"{k}={v:.3f}" for k, v in summary.items())
        print(f"{name:18s} {pretty}")
        eng.close()

    save_json(WORK / ("results_temporal_fake.json" if fake else "results_temporal.json"), results)


if __name__ == "__main__":
    main(fake="--fake" in sys.argv)
