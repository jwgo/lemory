"""LOCOMO evaluation: Lemory vs naive-RAG baseline, mem0-style protocol.

Per question: retrieve top-k from that conversation's session notes, generate
a short answer (same Gemini generator/prompt for every system), grade with an
LLM judge that sees only (question, gold, prediction). Also reports
evidence-recall@k (gold dialog turns found in retrieved text — no LLM).

Every (question, system) result is checkpointed to preds.jsonl, so quota
interruptions resume instead of restarting.

    python benchmarks/prep_locomo.py
    python benchmarks/run_locomo.py            # both systems
    python benchmarks/run_locomo.py lemory     # one system
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import WORK, load_env, normalize_answer, save_json

from lemory.config import LemoryConfig
from lemory.engine import Engine
from lemory.providers.gemini import GeminiClient
from lemory.retrieval.answer import build_context, build_prompt

OUT = WORK / "locomo"
K = 16
GEN_MODEL = "gemini-2.5-flash"  # identical generator for all systems

SYSTEMS = {
    "lemory": dict(mode="hybrid", graph=True),
    "vector": dict(mode="vector", graph=False),
}

GEN_SYSTEM = (
    "You answer questions about a two-person conversation using ONLY the "
    "provided session notes. Each note is dated — when the dialogue uses a "
    "relative time ('last week', 'four years ago', 'next month'), COMPUTE the "
    "absolute date/year from that note's date and answer with the computed "
    "value. Reply with the shortest exact answer: a few words, a date like "
    "'7 May 2023', or a comma-separated list when the question asks for "
    "multiple things — gather ALL matching items across the notes. For "
    "why/meaning questions, state the reason given in the conversation. "
    "No explanation. If the question asks for a preference, likelihood, or "
    "other inference, combine what the speakers said with common sense and "
    "give the most likely answer. If any related information exists in the "
    "notes, give your best supported answer instead of 'unknown'; reply "
    "'unknown' only when the notes contain nothing about the topic."
)

# graded the way mem0's LOCOMO evaluation grades: correct iff the generated
# answer captures the key information of the gold answer — paraphrase, extra
# detail, partial-but-essential coverage, and date-format differences all count
JUDGE_PROMPT = """Your task is to label a generated answer as CORRECT or WRONG.

QUESTION: {q}
GOLD ANSWER: {gold}
GENERATED ANSWER: {pred}

Label CORRECT if the generated answer captures the key information of the gold
answer that the question asks for, even if phrased differently, less complete
in wording, or more detailed. Dates count as correct when they refer to the
same day/period in any format. If the gold answer lists several items, the
generated answer is CORRECT when it includes the item(s) the question actually
asks about. For yes/no questions, a bare 'yes' or 'no' matching the gold's verdict is
CORRECT even without the gold's explanation. Label WRONG if it contradicts
the gold answer, names a different entity/date, or answers 'unknown' when
the gold has an answer.

Reply with exactly one word: yes (CORRECT) or no (WRONG)."""


def load_state() -> dict:
    state = {}
    f = OUT / "preds.jsonl"
    if f.exists():
        for line in f.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                state[(r["system"], r["conv"], r["q"])] = r
    return state


def append_state(row: dict) -> None:
    with open(OUT / "preds.jsonl", "a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


_TURN_IDX: dict[int, dict[str, str]] = {}


def turn_texts(conv_id: int, evidence: list[str]) -> list[str]:
    """Raw texts of gold evidence turns (D{sess}:{turn} ids)."""
    if conv_id not in _TURN_IDX:
        data = json.loads((Path(__file__).parent / "data" / "locomo" / "locomo10.json").read_text())
        c = data[conv_id]["conversation"]
        import re as _re
        idx = {}
        for sk in (k for k in c if _re.fullmatch(r"session_\d+", k)):
            for t in c[sk]:
                idx[t.get("dia_id")] = t.get("text", "") or ""
        _TURN_IDX[conv_id] = idx
    idx = _TURN_IDX[conv_id]
    return [idx[e] for e in evidence if e in idx and idx[e]]


def main(only: str | None = None) -> None:
    load_env()
    eval_set = json.loads((OUT / "eval_set.json").read_text())
    state = load_state()
    judge = GeminiClient(api_key=os.environ["GEMINI_API_KEY"],
                         llm_model=GEN_MODEL, llm_fallback_model="gemini-2.5-flash",
                         llm_rpm=60)

    engines: dict[int, Engine] = {}

    def engine_for(conv: int) -> Engine:
        if conv not in engines:
            cfg = LemoryConfig(
                vault=OUT / "vaults" / f"conv{conv}",
                data_dir=WORK / f"index-locomo-{conv}",
                llm_model=GEN_MODEL, llm_rpm=60,
            )
            engines[conv] = Engine(cfg)
            rep = engines[conv].index()
            if rep.embedded:
                print(f"  conv{conv}: indexed {rep.chunks} chunks ({rep.embedded} embedded)")
        return engines[conv]

    systems = {only: SYSTEMS[only]} if only else SYSTEMS
    for sys_name, opts in systems.items():
        done = 0
        for q in eval_set:
            key = (sys_name, q["conv"], q["q"])
            if key in state:
                continue
            eng = engine_for(q["conv"])
            from lemory.retrieval.intent import adaptive_k

            k_eff = adaptive_k(q["q"], K)  # same widening for every system
            hits = eng.search(q["q"], k=k_eff, **opts)
            ev_texts = turn_texts(q["conv"], q["evidence"])
            joined = " ".join(h.text for h in hits).lower()
            ev_found = sum(1 for t in ev_texts if t.lower() in joined)
            ctx = build_context(hits, max_chars=12000)
            pred = eng.llm.generate(
                build_prompt(ctx, q["q"]), system=GEN_SYSTEM,
                temperature=0.0, max_output_tokens=64,
            ).strip()
            verdict = judge.generate(
                JUDGE_PROMPT.format(q=q["q"], gold=q["answer"], pred=pred),
                temperature=0.0, max_output_tokens=8,
            ).strip().lower()
            row = {
                "system": sys_name, "conv": q["conv"], "q": q["q"],
                "category": q["category"], "gold": q["answer"], "pred": pred,
                "judge": 1 if verdict.startswith("yes") else 0,
                "ev_found": ev_found, "ev_total": len(ev_texts),
            }
            append_state(row)
            state[key] = row
            done += 1
            if done % 10 == 0:
                so_far = [state[k] for k in state if k[0] == sys_name]
                acc = sum(r["judge"] for r in so_far) / len(so_far)
                print(f"{sys_name}: {len(so_far)}/{len(eval_set)} judge-acc so far {acc:.3f}", flush=True)

    # ---------------- summarize ----------------
    results = {}
    cats = {1: "multi_hop", 2: "temporal", 3: "open_domain", 4: "single_hop"}
    for sys_name in SYSTEMS:
        rows = [r for (s, _, _), r in state.items() if s == sys_name]
        if not rows:
            continue
        summary = {"n": len(rows), "judge_acc": sum(r["judge"] for r in rows) / len(rows)}
        for cat, label in cats.items():
            sub = [r for r in rows if r["category"] == cat]
            if sub:
                summary[f"judge_{label}"] = sum(r["judge"] for r in sub) / len(sub)
        ev_rows = [r for r in rows if r["ev_total"]]
        if ev_rows:
            summary["evidence_recall@10"] = sum(r["ev_found"] / r["ev_total"] for r in ev_rows) / len(ev_rows)
        results[sys_name] = summary
        print(sys_name, json.dumps(summary, indent=1))
    save_json(WORK / "results_locomo.json", results)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else None)
