"""Compact vs full context: answer accuracy against context size.

Supermemory's LongMemEval result is framed as recall vs tokens added
(~720 tokens, 99.4% reduction). This measures Lemory's LLM-free aggregation
the same way on two of our judged sets:

  * multihop e2e sample (30 q, gold answers, F1/contain-EM)
  * temporal scenario ask() set (11 q, contains-answer check)

Same retrieval, same generator — only the context construction differs.

    python benchmarks/run_compact.py
"""

from __future__ import annotations

import json
import random
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import DATA, WORK, best_f1, load_env, make_engine, normalize_answer, save_json

from lemory.retrieval.answer import SYSTEM, build_context, build_prompt
from lemory.retrieval.compact import build_compact_context
from lemory.retrieval.intent import adaptive_k

K = 8


def run_set(engine, questions, style: str, now=None) -> dict:
    f1s, ems, ctx_chars = [], [], []
    for q in questions:
        k = adaptive_k(q["q"], K)
        hits = engine.search(q["q"], k=k)
        if style == "compact":
            ctx = build_compact_context(engine, q["q"], hits)
        else:
            ctx = build_context(hits)
        ctx_chars.append(len(ctx))
        pred = engine.llm.generate(
            build_prompt(ctx, q["q"], instruction="Answer with the shortest exact phrase only."),
            system=SYSTEM, temperature=0.0, max_output_tokens=64,
        ).strip()
        golds = q.get("answers") or [q["answer"]]
        f1s.append(best_f1(pred, golds))
        ems.append(float(any(normalize_answer(g) in normalize_answer(pred) for g in golds)))
    n = len(questions)
    return {
        "n": n, "f1": sum(f1s) / n, "contain_em": sum(ems) / n,
        "avg_context_chars": sum(ctx_chars) / n,
        "approx_context_tokens": sum(ctx_chars) / n / 4,
    }


def main() -> None:
    load_env()
    results = {}

    # --- multihop (30-question e2e sample, same seed as run_e2e) ---
    questions = json.loads((DATA / "multihop" / "questions.json").read_text())
    rng = random.Random(11)
    two = [q for q in questions if q["hops"] == 2]
    one = [q for q in questions if q["hops"] == 1]
    rng.shuffle(two), rng.shuffle(one)
    sample = two[:21] + one[:9]
    eng = make_engine(DATA / "multihop" / "vault", tag="multihop")
    eng.index()
    for style in ("full", "compact"):
        results[f"multihop_{style}"] = run_set(eng, sample, style)
        print(f"multihop {style}: {json.dumps(results[f'multihop_{style}'])}", flush=True)
    eng.close()

    # --- temporal scenario (Korean memory questions) ---
    tq = json.loads((WORK / "temporal" / "queries.json").read_text())
    eng = make_engine(WORK / "temporal" / "vault", tag="temporal-real")
    eng.cfg.data_dir = WORK / "index-temporal-real"
    eng.now = lambda: datetime(2026, 7, 9, 18).timestamp()
    eng.index()
    for style in ("full", "compact"):
        results[f"temporal_{style}"] = run_set(eng, tq, style)
        print(f"temporal {style}: {json.dumps(results[f'temporal_{style}'])}", flush=True)
    eng.close()

    save_json(WORK / "results_compact.json", results)


if __name__ == "__main__":
    main()
