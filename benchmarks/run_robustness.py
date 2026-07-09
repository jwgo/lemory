"""Robustness benchmark: does retrieval survive real-world query phrasing?

For every multihop question and each committed variant (paraphrase / korean /
keyword / typo), measure full-support@8 per system. The gold notes are those
of the original question; the variant only changes the phrasing.

Optionally include Lemory's LLM stages tier (--stages) to measure what query
expansion buys on hard phrasings.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import DATA, SYSTEMS, WORK, load_env, make_engine, prewarm_queries, save_json

K = 8


def run(with_stages: bool = False) -> None:
    load_env()
    questions = json.loads((DATA / "multihop" / "questions.json").read_text())
    variants = json.loads((DATA / "multihop" / "robust_queries.json").read_text())

    engine = make_engine(DATA / "multihop" / "vault", tag="multihop")
    engine.index()

    systems = dict(SYSTEMS)
    stage_kinds = {"paraphrase", "korean", "typo"}  # where base lemory is weakest
    if with_stages:
        systems = {"lemory+expand": dict(mode="hybrid", graph=True, expand=True)}

    # prewarm every query string we'll search (batched embeddings)
    all_queries = [q["q"] for q in questions]
    for q in questions:
        all_queries.extend(variants.get(q["q"], {}).values())
    prewarm_queries(engine, all_queries)

    kinds = ["original", "paraphrase", "korean", "keyword", "typo"]
    results: dict[str, dict] = {}
    for sys_name, opts in systems.items():
        per_kind: dict[str, list[bool]] = {k: [] for k in kinds}
        t_start = time.time()
        for q in questions:
            gold = set(q["gold_notes"])
            qmap = {"original": q["q"], **variants.get(q["q"], {})}
            for kind in kinds:
                text = qmap.get(kind)
                if not text or (with_stages and kind not in stage_kinds):
                    continue
                hits = engine.search(text, k=K, **opts)
                per_kind[kind].append(gold <= {h.title for h in hits})
        results[sys_name] = {
            f"full_support@{K}_{kind}": (sum(v) / len(v) if v else None)
            for kind, v in per_kind.items()
        }
        results[sys_name]["seconds"] = time.time() - t_start
        pretty = "  ".join(
            f"{kind}={results[sys_name][f'full_support@{K}_{kind}']:.3f}"
            for kind in kinds if per_kind[kind]
        )
        print(f"{sys_name:16s} {pretty}")

    out_file = WORK / ("results_robustness_stages.json" if with_stages else "results_robustness.json")
    if with_stages and (WORK / "results_robustness.json").exists():
        pass  # base results stay in their own file
    save_json(out_file, results)


if __name__ == "__main__":
    run(with_stages="--stages" in sys.argv)
