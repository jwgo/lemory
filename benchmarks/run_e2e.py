"""End-to-end QA benchmark: same Gemini generator, different retrievers.

Measures what the user experiences: answer correctness (SQuAD-style token F1
and containment-EM against gold answers). The generator prompt/model are
identical across systems; only retrieval differs.

Usage: python run_e2e.py multihop 40
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (DATA, WORK, best_f1, load_env, make_engine, normalize_answer,
                    prewarm_queries, save_json)

from lemory.answer import SYSTEM, build_context

SYSTEMS = {
    "lemory": dict(mode="hybrid", graph=True),
    "vector": dict(mode="vector", graph=False),
    "bm25": dict(mode="bm25", graph=False),
}
K = 8


def main() -> None:
    load_env()
    bench = sys.argv[1] if len(sys.argv) > 1 else "multihop"
    n_q = int(sys.argv[2]) if len(sys.argv) > 2 else 40

    if bench == "multihop":
        vault = DATA / "multihop" / "vault"
        questions = json.loads((DATA / "multihop" / "questions.json").read_text())
    else:
        vault = WORK / "squad_vault"
        questions = json.loads((WORK / "squad_questions.json").read_text())
    questions = questions[:n_q]

    eng = make_engine(vault, tag=bench)
    eng.index()
    prewarm_queries(eng, [q["q"] for q in questions])

    out_file = WORK / f"results_e2e_{bench}.json"
    state = json.loads(out_file.read_text()) if out_file.exists() else {"preds": {}}

    # question-major order with per-question model alternation: every system
    # answers a given question with the SAME model, so the cross-system
    # comparison stays generator-fair even when quota forces model rotation
    models = [eng.cfg.llm_model, eng.cfg.llm_fallback_model]
    for i, q in enumerate(questions):
        qid = f"{i}:{q['q'][:40]}"
        model = models[i % len(models)]
        for sysname, kw in SYSTEMS.items():
            preds = state["preds"].setdefault(sysname, {})
            if qid in preds:
                continue
            hits = eng.search(q["q"], k=K, **kw)
            context = build_context(hits)
            prompt = (
                f"NOTES:\n{context}\n\nQUESTION: {q['q']}\n\n"
                "Answer with the shortest exact phrase only (no sentence)."
            )
            try:
                text = eng.llm.generate(prompt, system=SYSTEM, temperature=0.0,
                                        max_output_tokens=256, model=model)
            except Exception as e:
                print(f"  gen failed ({e}); stopping this run — rerun to resume")
                save_json(out_file, state)
                raise SystemExit(1)
            preds[qid] = {"pred": text.strip(), "answers": q["answers"], "hops": q.get("hops", 1)}
            save_json(out_file, state)
            print(f"q{i+1}/{len(questions)} {sysname} [{model.rsplit('-',1)[-1]}]: {text.strip()[:60]}", flush=True)

    # score (strip inline "[n]" citation markers before comparing)
    import re

    def clean(p: str) -> str:
        return re.sub(r"\s*\[\d+\]", "", p).strip()

    summary = {}
    for sysname, preds in state["preds"].items():
        rows = list(preds.values())
        if not rows:
            continue
        f1 = sum(best_f1(clean(r["pred"]), r["answers"]) for r in rows) / len(rows)
        em = sum(
            any(normalize_answer(a) in normalize_answer(clean(r["pred"])) for a in r["answers"])
            for r in rows
        ) / len(rows)
        summary[sysname] = {"f1": f1, "contain_em": em, "n": len(rows)}
        for hops in (1, 2):
            sub = [r for r in rows if r.get("hops") == hops]
            if sub:
                summary[sysname][f"f1_hops{hops}"] = sum(
                    best_f1(clean(r["pred"]), r["answers"]) for r in sub) / len(sub)
        print(sysname, summary[sysname])
    state["summary"] = summary
    save_json(out_file, state)
    print(f"saved -> {out_file}")


if __name__ == "__main__":
    main()
