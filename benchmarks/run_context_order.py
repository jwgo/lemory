"""A/B: context presentation order for ask() — fusion-rank vs CDS-inspired
curriculum ordering (arXiv:2605.13511). Same retrieval hits, same generator,
same prompt; ONLY the reading order of the evidence blocks differs.

    python benchmarks/run_context_order.py [n_questions] [k]

Runs on KorQuAD (real Korean Wikipedia + human questions). Uses LLM quota:
n_questions × 2 generations.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import WORK, best_f1, load_env, make_engine, normalize_answer, prewarm_queries, save_json
from run_korquad import VAULT, prepare

from lemory.retrieval.answer import SYSTEM, build_context, build_prompt
from lemory.retrieval.curriculum import curriculum_order, path_smoothness

N = int(sys.argv[1]) if len(sys.argv) > 1 else 40
K = int(sys.argv[2]) if len(sys.argv) > 2 else 12


def main() -> None:
    load_env()
    questions = prepare()
    engine = make_engine(VAULT, tag="korquad")
    engine.index()
    rng = random.Random(29)
    sample = rng.sample(questions, N)
    prewarm_queries(engine, [q["q"] for q in sample])

    out_file = WORK / "results_context_order.json"
    results = json.loads(out_file.read_text()) if out_file.exists() else {}
    per_q = results.setdefault("per_q", [])
    done = {(p["q"], p["order"]) for p in per_q}

    smooth = {"rank": [], "curriculum": []}
    for i, q in enumerate(sample):
        hits = engine.search(q["q"], k=K, mode="hybrid", graph=True)
        qv = engine.embed_query_cached(q["q"])
        variants = {
            "rank": hits,
            "curriculum": curriculum_order(engine, qv, hits),
        }
        for order, ordered_hits in variants.items():
            smooth[order].append(path_smoothness(engine, ordered_hits))
            if (q["q"], order) in done:
                continue
            try:
                pred = engine.llm.generate(
                    build_prompt(build_context(ordered_hits, max_chars=16000), q["q"],
                                 instruction="정답 구절만 짧게 답하세요."),
                    system=SYSTEM, temperature=0.0, max_output_tokens=64,
                ).strip()
            except RuntimeError as e:
                # some real-wiki passages trip the API safety filter
                # (PROHIBITED_CONTENT); drop the QUESTION, not the run — the
                # summary pairs by question, so fairness is preserved
                print(f"  skip (generation blocked): {q['q'][:40]}… ({str(e)[:60]})", flush=True)
                break
            per_q.append({
                "q": q["q"], "order": order, "pred": pred, "gold": q["answers"],
                "f1": best_f1(pred, q["answers"]),
                "em": float(any(normalize_answer(g) in normalize_answer(pred)
                                for g in q["answers"])),
            })
            save_json(out_file, results)  # checkpoint per generation
        if (i + 1) % 5 == 0:
            print(f"{i+1}/{N}", flush=True)

    # summarize only questions answered under BOTH orders — a question skipped
    # (safety filter) or half-done must not tilt the comparison
    counts: dict[str, set] = {"rank": set(), "curriculum": set()}
    for p in per_q:
        counts[p["order"]].add(p["q"])
    paired = counts["rank"] & counts["curriculum"]
    summary = {}
    for order in ("rank", "curriculum"):
        rows = [p for p in per_q if p["order"] == order and p["q"] in paired]
        summary[order] = {
            "f1": sum(p["f1"] for p in rows) / max(1, len(rows)),
            "contain_em": sum(p["em"] for p in rows) / max(1, len(rows)),
            "mean_path_smoothness": sum(smooth[order]) / max(1, len(smooth[order])),
            "n": len(rows),
        }
    results["summary"] = {**summary, "k": K}
    save_json(out_file, results)
    print(json.dumps(results["summary"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
